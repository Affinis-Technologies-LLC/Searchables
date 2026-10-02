"""
The app's local web server: a JSON API over the library, collections, code index and background
indexer, and the browser front end (web/, built into src/server/static) served beside it.

Everything except signing in needs a session cookie. The library's database connection isn't meant
for several threads at once, so API calls take turns (one user, short calls); PDFs are streamed
outside that queue. Requests that change anything must carry the X-Requested-With header the front
end sends, which a page from another site can't add.
"""
import csv
import dataclasses
import io
import json
import re
import sqlite3
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence
from urllib.parse import quote

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from src import auth, config
from src.code.models import Usage
from src.code.parser import JAVA
from src.code.store import CodeStore
from src.extractor.identifiers import identifier_key
from src.extractor.pdf import ocr_available
from src.models import Document, TextBlock
from src.research import export
from src.research.collections import CollectionStore, pin_key
from src.research.compare import compare, provision_change, to_markdown, word_diff_html
from src.research.glossary import build_acronyms, build_glossary, expand_acronyms, terms_in_text
from src.search import semantic
from src.search.indexer import ADD, CODE, EMBED, REINDEX, Indexer
from src.search.library import (CONTENT_KINDS, IDENTIFIER_GROUP_TITLES, PROVISION_FILTERS, RELATED_GROUPS, Library,
                                table_caption, uses_meaning)
from src.utils.formatting import highlight_values
from src.viewer.render import hit_rects

COOKIE = "searchables_session"
STATIC = Path(__file__).parent / "static"
_CODE_PIN_LINES = 60        # Lines of a symbol's source kept when it's pinned
_CONTENT_SECURITY = ("default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; "
                     "img-src 'self' data: blob:; font-src 'self' data:; worker-src 'self' blob:; "
                     "connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")


class NotFound(Exception):
    pass


class Services:
    """What the API works on, created on first use (so importing this module touches nothing)."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.sessions = auth.Sessions()
        self._ready = False

    def start(self) -> None:
        with self.lock:
            if not self._ready:
                self.library = Library()
                self.collections = CollectionStore(self.library.conn)
                self.code = CodeStore(self.library.conn)
                self.indexer = Indexer()
                self._glossaries: Dict[tuple, list] = {}
                self._comparisons: Dict[tuple, list] = {}
                self.ocr = ocr_available()   # Looked for once: asking starts the tesseract program
                self._ready = True

    def document(self, doc_id: int) -> Document:
        doc = self.library.get_document(doc_id)
        if doc is None:
            raise NotFound("That document is no longer in the library.")
        return doc

    def block(self, block_id: int) -> TextBlock:
        block = self.library.get_block(block_id)
        if block is None:
            raise NotFound("That passage is no longer in the library (its document was re-indexed or removed).")
        return block

    def glossary(self, doc: Document) -> list:
        # The stamp changes whenever the document is re-indexed with different results
        stamp = (doc.id, doc.block_count, doc.page_count, doc.extract_version)
        if stamp not in self._glossaries:
            if len(self._glossaries) > 100:
                self._glossaries.clear()
            blocks = self.library.document_blocks(doc.id)
            self._glossaries[stamp] = build_glossary(blocks) + build_acronyms(blocks, self.library.document_tables(doc.id))
        return self._glossaries[stamp]

    def acronyms(self, doc_ids: Sequence[int]) -> Dict[str, str]:
        """Acronyms and what they stand for, from the documents in scope (all of them when none are chosen)."""
        found: Dict[str, str] = {}
        for doc in self.library.list_documents():
            if not doc_ids or doc.id in doc_ids:
                for term in self.glossary(doc):
                    if term.acronym:
                        found.setdefault(term.term, term.definition)
        return found

    def comparison(self, old: Document, new: Document) -> list:
        stamp = tuple((d.id, d.block_count, d.page_count, d.extract_version) for d in (old, new))
        if stamp not in self._comparisons:
            if len(self._comparisons) > 10:
                self._comparisons.clear()
            self._comparisons[stamp] = compare(self.library.document_blocks(old.id), self.library.document_blocks(new.id))
        return self._comparisons[stamp]


services = Services()


@dataclasses.dataclass
class Call:
    """One API request: path and query parameters, and the JSON (or raw) body."""
    request: Request
    path: Dict[str, Any]
    query: Any
    data: Dict[str, Any]
    body: bytes

    def ints(self, name: str) -> List[int]:
        return [int(v) for v in self.query.get(name, "").split(",") if v.strip().lstrip("-").isdigit()]

    def words(self, name: str) -> List[str]:
        return [v for v in self.query.get(name, "").split(",") if v]

    def flag(self, name: str) -> bool:
        return self.query.get(name, "") in ("1", "true")


def plain(value: Any) -> Any:
    """Dataclasses, rows and tuples as JSON-ready dicts and lists."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        out = {f.name: plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
        if isinstance(value, TextBlock):
            out.update(clause=value.clause, display_page=value.display_page,
                       pin_key=pin_key(value) if value.doc_id is not None else None)
        return out
    if isinstance(value, sqlite3.Row):
        return {key: plain(value[key]) for key in value.keys()}
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [plain(item) for item in value]
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):   # numpy scalars
        return value.item()
    return value


# ---- Routing ------------------------------------------------------------------------------------

_routes: List[Route] = []


def api(method: str, path: str, public: bool = False, locked: bool = True) -> Callable:
    """Registers an API handler: it's given a Call, and returns JSON-ready data or a Response."""
    def register(handler: Callable[[Call], Any]) -> Callable:
        async def endpoint(request: Request) -> Response:
            if not public and not services.sessions.active(request.cookies.get(COOKIE)):
                return JSONResponse({"error": "Sign in to continue."}, status_code=401)
            if method != "GET" and request.headers.get("x-requested-with") != "searchables":
                return JSONResponse({"error": "This request didn't come from the app."}, status_code=403)
            body = await request.body() if method != "GET" else b""
            data: Dict[str, Any] = {}
            if body and request.headers.get("content-type", "").startswith("application/json"):
                try:
                    data = json.loads(body)
                except ValueError:
                    return JSONResponse({"error": "The request wasn't valid JSON."}, status_code=400)
            call = Call(request, dict(request.path_params), request.query_params, data, body)

            def run() -> Any:
                services.start()
                if not locked:
                    return handler(call)
                with services.lock:
                    return handler(call)
            try:
                result = await run_in_threadpool(run)
            except NotFound as e:
                return JSONResponse({"error": str(e) or "Not found."}, status_code=404)
            except (ValueError, sqlite3.OperationalError) as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            return result if isinstance(result, Response) else JSONResponse(plain(result))
        _routes.append(Route("/api" + path, endpoint, methods=[method]))
        return handler
    return register


def _download(content: Any, filename: str, media_type: str) -> Response:
    safe = re.sub(r"[^\w\- .]+", "", filename).strip() or "download"
    return Response(content, media_type=media_type,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(safe)}"})


# ---- Session ------------------------------------------------------------------------------------

def _signed_in(data: dict) -> Response:
    response = JSONResponse(data)
    response.set_cookie(COOKIE, services.sessions.start(), httponly=True, samesite="strict", path="/")
    return response


@api("GET", "/session", public=True)
def session(c: Call) -> dict:
    return {"authenticated": services.sessions.active(c.request.cookies.get(COOKIE)),
            "setup": auth.load() is None, "min_password": config.MIN_PASSWORD_LENGTH,
            "idle_minutes": config.SESSION_IDLE_MINUTES, "auth_file": str(config.AUTH_FILE)}


@api("POST", "/session/setup", public=True)
def session_setup(c: Call) -> Response:
    if auth.load() is not None:
        raise ValueError("A password has already been set.")
    problem = auth.password_problem(c.data.get("password", ""), c.data.get("confirm", ""))
    if problem:
        raise ValueError(problem)
    auth.save(c.data["password"])
    return _signed_in({"authenticated": True})


@api("POST", "/session/login", public=True)
def session_login(c: Call) -> Response:
    locked = services.sessions.locked_for()
    if locked:
        return JSONResponse({"error": f"Too many incorrect attempts. Try again in {locked} seconds."}, status_code=429)
    if not auth.verify(c.data.get("password", "")):
        services.sessions.failed()
        return JSONResponse({"error": "Incorrect password."}, status_code=401)
    services.sessions.succeeded()
    return _signed_in({"authenticated": True})


@api("POST", "/session/logout", public=True)
def session_logout(c: Call) -> Response:
    services.sessions.end(c.request.cookies.get(COOKIE))
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(COOKIE, path="/")
    return response


@api("POST", "/session/password")
def session_password(c: Call) -> dict:
    if not auth.verify(c.data.get("current", "")):
        raise ValueError("The current password is incorrect.")
    problem = auth.password_problem(c.data.get("new", ""), c.data.get("confirm", ""))
    if problem:
        raise ValueError(problem)
    auth.save(c.data["new"])
    services.sessions.end_others(c.request.cookies.get(COOKIE))   # Browsers signed in with the old password
    return {"changed": True}


# ---- Overview -----------------------------------------------------------------------------------

def _job(job) -> dict:
    return {"id": job.id, "kind": job.kind, "name": job.name, "status": job.status, "stage": job.stage,
            "done": job.done, "total": job.total, "result": job.result, "warning": job.warning}


@api("GET", "/state")
def state(c: Call) -> dict:
    """Everything the front end keeps on screen: documents, collections, codebases and indexing progress."""
    s = services
    busy, scanning = s.indexer.pending_doc_ids(), s.indexer.pending_codebases()
    s.collections.ensure_default()
    return {
        "documents": [{**plain(d), "outdated": d.extract_version < config.EXTRACTOR_VERSION,
                       "meaning": d.embedding_model == config.EMBEDDING_ID, "busy": d.id in busy}
                      for d in s.library.list_documents()],
        "collections": s.collections.list_collections(),
        "codebases": [{**plain(b), "scanning": b.id in scanning} for b in s.code.list_codebases()],
        "jobs": {"active": [_job(j) for j in s.indexer.active()],
                 "finished": [_job(j) for j in s.indexer.finished()[-8:]]},
        "recent": s.library.recent_searches(),
        "ocr": s.ocr,
        "meaning_model": semantic.model_files_present(),
        "content_kinds": CONTENT_KINDS,
        "provisions": PROVISION_FILTERS,
        "max_results": config.DEFAULT_MAX_RESULTS,
    }


# ---- Documents ----------------------------------------------------------------------------------

@api("POST", "/documents")
def add_document(c: Call) -> dict:
    name = Path(c.query.get("filename", "document.pdf")).name
    if not c.body:
        raise ValueError("The file is empty.")
    return _job(services.indexer.submit(ADD, name, file_bytes=c.body))


@api("PATCH", "/documents/{id:int}")
def rename_document(c: Call) -> dict:
    title = " ".join(str(c.data.get("title", "")).split())
    if not title:
        raise ValueError("Give the document a title.")
    services.library.rename_document(services.document(c.path["id"]).id, title)
    return {"title": title}


@api("DELETE", "/documents/{id:int}")
def delete_document(c: Call) -> dict:
    if c.path["id"] in services.indexer.pending_doc_ids():
        raise ValueError("That document is being indexed; delete it when that's done.")
    services.library.delete_document(c.path["id"])
    return {"deleted": True}


@api("POST", "/documents/{id:int}/{action}")
def index_document(c: Call) -> dict:
    kind = {"reindex": REINDEX, "embed": EMBED}.get(c.path["action"])
    doc = services.document(c.path["id"])
    if kind is None:
        raise NotFound()
    if doc.id in services.indexer.pending_doc_ids():
        raise ValueError("That document is already being indexed.")
    return _job(services.indexer.submit(kind, doc.title, doc_id=doc.id))


@api("GET", "/documents/{id:int}/file", locked=False)
def document_file(c: Call) -> Response:
    with services.lock:
        doc = services.document(c.path["id"])
    path = services.library.pdf_path(doc.sha256)
    if not path.exists():
        raise NotFound("The stored PDF is missing; delete the document and add the file again.")
    return FileResponse(path, media_type="application/pdf", headers={"Cache-Control": "private, max-age=3600"})


@lru_cache(maxsize=256)
def _hit_rects(path: str, page: int, terms: tuple) -> list:
    return hit_rects(Path(path), page, terms)


def _table(block: TextBlock, rows: Optional[Sequence[int]] = None) -> Optional[dict]:
    """A table as data: joined with its continuations, or (with `rows`) just those rows of this page's part."""
    parts = services.library.table_parts(block)
    if not parts:
        return None
    if rows is not None:
        part = next((data for b, data in parts if b.id == block.id), parts[0][1])
        return {"caption": table_caption(block, part), "columns": part.columns,
                "rows": [part.rows[r - 1] for r in rows if 0 < r <= len(part.rows)]}
    return services.library.joined_table(block)


_PAIR = re.compile(r"^([A-Z]+)/([A-Z]+) (\d+)/(\d+)$")


def _as_written(values: Sequence[str]) -> List[str]:
    """
    The ways an identifier may be written on a page, to highlight it: a pair such as "GRP/ITM 281/001"
    also appears as "GRP 281/ITM 001", and in a table under a "GRP/ITM" heading as just "281/001".
    """
    found = list(values)
    for value in values:
        pair = _PAIR.match(value)
        if pair:
            a, b, n, m = pair.groups()
            found += [f"{a} {n}/{b} {m}", f"{a} {n}, {b} {m}", f"{n}/{m}"]
    return sorted(set(found), key=len, reverse=True)


def _terms(terms: Sequence) -> list:
    return [{"term": t.term, "synonyms": t.synonyms, "clause_num": t.clause_num, "definition": t.definition,
             "doc_id": t.doc_id, "page": t.page, "bbox": t.bbox, "acronym": t.acronym} for t in terms]


@api("GET", "/documents/{id:int}/pages/{page:int}")
def document_page(c: Call) -> dict:
    """A page's passages, tables, references and defined terms, and where a search's hits are on it."""
    library = services.library
    doc, page = services.document(c.path["id"]), c.path["page"]
    if not 1 <= page <= doc.page_count:
        raise NotFound("That page isn't in the document.")
    blocks = library.page_blocks(doc.id, page)
    query, identifier, children = c.query.get("q", "").strip(), c.query.get("identifier", "").strip(), c.flag("children")
    hit_pages, terms, matches = [], (), {}
    if identifier:
        values = library.identifier_values_on_page(doc.id, page, identifier, children)
        texts = {b.id: b.text for b in blocks}
        matches = {bid: highlight_values(texts[bid], _as_written(found)) for bid, found in values.items() if bid in texts}
        terms = tuple(_as_written(sorted({v for found in values.values() for v in found})))
        hit_pages = library.identifier_pages(doc.id, identifier, children)
    elif query:
        hit_pages = library.hit_pages(query, doc.id)
        terms = tuple(library.page_hit_terms(query, doc.id, page))
        matches = library.page_matches(query, doc.id, page)
    return {
        "page": page,
        "page_label": next((b.display_page for b in blocks), str(page)),
        "blocks": blocks,
        "matches": matches,
        "hits": _hit_rects(str(library.pdf_path(doc.sha256)), page, terms) if terms else [],
        "hit_pages": hit_pages,
        "tables": {b.id: _table(b) for b in blocks if b.kind == "table"},
        "references": [{"kind": r.ref.kind, "target": r.ref.target, "doc_id": r.doc_id, "page": r.page, "bbox": r.bbox,
                        "doc_title": r.doc_title, "block_id": r.block_id} for r in library.page_refs(doc.id, page)],
        "referenced_by": [{"kind": ref.kind, "target": ref.target, "block": block}
                          for ref, block in library.referenced_from(doc.id, page)],
        "terms": _terms(terms_in_text(services.glossary(doc), " ".join(b.text for b in blocks))),
    }


@api("GET", "/documents/{id:int}/outline")
def document_outline(c: Call) -> list:
    """The document's clauses in order, each where it starts: a table of contents to navigate by."""
    doc = services.document(c.path["id"])
    rows = services.library.conn.execute(
        "SELECT id, page, clause_num, clause_title, clause_path, x0, y0, x1, y1, MIN(seq) FROM blocks "
        "WHERE doc_id = ? AND (clause_num != '' OR clause_title != '') GROUP BY clause_path ORDER BY MIN(seq)",
        (doc.id,)).fetchall()
    return [{"block_id": r["id"], "page": r["page"], "num": r["clause_num"], "title": r["clause_title"],
             "level": r["clause_path"].count(" › ") + 1,
             "bbox": [r["x0"], r["y0"], r["x1"], r["y1"]] if r["x0"] is not None else None} for r in rows]


@api("GET", "/documents/{id:int}/glossary")
def document_glossary(c: Call) -> list:
    return _terms(services.glossary(services.document(c.path["id"])))


@api("GET", "/documents/{id:int}/health")
def document_health(c: Call) -> list:
    return services.library.health(services.document(c.path["id"]).id)


@api("GET", "/documents/{id:int}/identifiers")
def identifier_families(c: Call) -> list:
    doc = services.document(c.path["id"])
    return [{**plain(f), "enabled": f.enabled} for f in services.library.identifier_families(doc.id)]


@api("PUT", "/documents/{id:int}/identifiers")
def set_identifier_family(c: Call) -> list:
    """{"family": …, "enabled": true/false/null}; null returns it to automatic. Without a family, resets them all."""
    doc = services.document(c.path["id"])
    if "family" in c.data:
        services.library.set_family_enabled(doc.id, c.data["family"], c.data.get("enabled"))
    else:
        services.library.reset_families(doc.id)
    return identifier_families(c)


# ---- Search -------------------------------------------------------------------------------------

def _block_terms(block: TextBlock, docs: Dict[int, Document]) -> list:
    doc = docs.get(block.doc_id)
    return _terms(terms_in_text(services.glossary(doc), block.text)) if doc and block.kind == "text" else []


@api("GET", "/search")
def search(c: Call) -> dict:
    library = services.library
    query = c.query.get("q", "")
    by_position = c.query.get("order") == "document"
    limit = min(int(c.query.get("limit", config.DEFAULT_MAX_RESULTS)), config.MAX_DOCUMENT_ORDER_RESULTS)
    # The model doesn't know the documents' acronyms: a plain-word search has them spelled out (and the reverse)
    expansions = expand_acronyms(query, services.acronyms(c.ints("docs"))) if uses_meaning(query) else []
    expanded = " ".join([query, *(f"{acronym} {meaning}" for acronym, meaning in expansions)]) if expansions else ""
    results, total = library.search(
        query, doc_ids=c.ints("docs"), limit=config.MAX_DOCUMENT_ORDER_RESULTS if by_position else limit,
        document_order=by_position, kinds=c.words("kinds"), provisions=c.words("provisions"), expanded=expanded)
    library.record_search(query)
    docs = {d.id: d for d in library.list_documents()}
    return {
        "total": total,
        "by_meaning": uses_meaning(query),
        "expanded": [{"acronym": acronym, "meaning": meaning} for acronym, meaning in expansions],
        "results": [{"block": r.block, "doc_title": r.doc_title, "html": r.highlighted_text, "match": r.match,
                     "similarity": r.similarity, "score": r.score, "citation": r.citation,
                     "table": _table(r.block, r.rows) if r.rows else None,
                     "terms": _block_terms(r.block, docs)} for r in results],
    }


@api("GET", "/identifiers")
def identifier_search(c: Call) -> dict:
    """An identifier's passages grouped by role, with the identifiers related to it (or suggestions when it's unknown)."""
    library = services.library
    query, children, doc_ids = c.query.get("q", "").strip(), c.flag("children"), c.ints("docs")
    if not query:
        raise ValueError("Enter an identifier to search for.")
    hits = library.identifier_search(query, children, doc_ids=doc_ids, kinds=c.words("kinds"),
                                     provisions=c.words("provisions"))
    library.record_search(query)
    outdated = [d for d in library.outdated_documents() if not doc_ids or d.id in doc_ids]
    return {
        "key": identifier_key(query),
        "hits": [{"block": h.block, "doc_title": h.doc_title, "group": h.group, "values": h.values,
                  "html": highlight_values(h.block.text, h.values) if h.group != "table" else None,
                  "table": _table(h.block, h.rows) if h.group == "table" else None,
                  "citation": ", ".join(p for p in (h.doc_title, h.block.label or h.block.clause,
                                                    f"p. {h.block.display_page}") if p)} for h in hits],
        "groups": IDENTIFIER_GROUP_TITLES,
        "related": library.related_identifiers(query, children, doc_ids=doc_ids),
        "suggestions": [] if hits else library.identifier_suggestions(query, doc_ids=doc_ids),
        "outdated": len(outdated),
    }


@api("GET", "/catalogue")
def catalogue(c: Call) -> list:
    """Every identifier of the switched-on patterns (messages, words, data elements…), to browse."""
    return services.library.catalogue(c.ints("docs"))


@api("GET", "/catalogue/entry")
def catalogue_entry(c: Call) -> dict:
    text = c.query.get("id", "").strip()
    if not text:
        raise ValueError("Choose an identifier.")
    detail = services.library.identifier_detail(text, c.ints("docs"))
    detail["documents"] = [{"id": doc_id, "title": title} for doc_id, title in detail["documents"]]
    return detail


@api("GET", "/catalogue/changes")
def catalogue_changes(c: Call) -> dict:
    old, new = services.document(int(c.query.get("old", 0))), services.document(int(c.query.get("new", 0)))
    return services.library.identifier_changes(c.query.get("id", ""), old.id, new.id)


@api("GET", "/blocks/{id:int}/related")
def related(c: Call) -> dict:
    block = services.block(c.path["id"])
    doc = services.library.get_document(block.doc_id)
    terms = terms_in_text(services.glossary(doc), block.text) if doc and block.kind == "text" else []
    groups = services.library.related_passages(block, terms)
    return {"block": block, "doc_title": doc.title if doc else "",
            "groups": [{"key": key, "title": RELATED_GROUPS[key], "items": items} for key, items in groups.items()]}


@api("GET", "/blocks/{id:int}/table")
def block_table(c: Call) -> dict:
    table = _table(services.block(c.path["id"]))
    if table is None:
        raise NotFound("That passage isn't a table.")
    return table


# ---- Collections --------------------------------------------------------------------------------

@api("POST", "/collections")
def create_collection(c: Call) -> dict:
    return {"id": services.collections.create(str(c.data.get("name", "")))}


@api("PATCH", "/collections/{id:int}")
def rename_collection(c: Call) -> dict:
    services.collections.rename(c.path["id"], str(c.data.get("name", "")))
    return {"renamed": True}


@api("DELETE", "/collections/{id:int}")
def delete_collection(c: Call) -> dict:
    services.collections.delete(c.path["id"])
    return {"deleted": True}


@api("GET", "/collections/{id:int}/pins")
def pins(c: Call) -> dict:
    live = {d.id for d in services.library.list_documents()}
    return {"pins": [{**plain(p), "available": p.doc_id in live} for p in services.collections.pins(c.path["id"])],
            "keys": sorted(services.collections.pinned_keys(c.path["id"]))}


@api("POST", "/collections/{id:int}/pins")
def add_pin(c: Call) -> dict:
    """{"block_id": …, "query": …} pins a passage, table or figure; {"symbol_id": …} pins a symbol's source."""
    if "symbol_id" in c.data:
        symbol = services.code.symbol(c.data["symbol_id"])
        codebase = services.code.get(symbol.codebase_id) if symbol else None
        if symbol is None or codebase is None:
            raise NotFound("That symbol is no longer in the code index.")
        text = "\n".join(services.code.lines(symbol.file_id)[symbol.line - 1:symbol.end_line][:_CODE_PIN_LINES])
        block = TextBlock(id=0, page=symbol.line, text=text, word_count=len(text.split()), page_label=str(symbol.line),
                          kind="code", label=symbol.location, clause_title=symbol.qualified)
        services.collections.add_pin(c.path["id"], block, codebase.name, f"{codebase.name}, {symbol.location}",
                                     query=symbol.qualified)
        return {"pinned": True}
    block = services.block(c.data.get("block_id"))
    doc = services.document(block.doc_id)
    citation = ", ".join(p for p in (doc.title, block.label or block.clause, f"p. {block.display_page}") if p)
    table = _table(block) if block.kind == "table" else None
    services.collections.add_pin(c.path["id"], block, doc.title, citation, str(c.data.get("query", "")),
                                 {k: table[k] for k in ("caption", "columns", "rows")} if table else None,
                                 marking=doc.distribution)
    return {"pinned": True, "key": pin_key(block)}


@api("DELETE", "/collections/{id:int}/pins")
def remove_pin_by_key(c: Call) -> dict:
    services.collections.remove_pin_key(c.path["id"], c.query.get("key", ""))
    return {"pinned": False}


@api("PATCH", "/pins/{id:int}")
def update_pin(c: Call) -> dict:
    services.collections.update_note(c.path["id"], str(c.data.get("note", "")))
    return {"saved": True}


@api("DELETE", "/pins/{id:int}")
def remove_pin(c: Call) -> dict:
    services.collections.remove_pin(c.path["id"])
    return {"removed": True}


@api("GET", "/collections/{id:int}/export")
def export_collection(c: Call) -> Response:
    collection = next((x for x in services.collections.list_collections() if x.id == c.path["id"]), None)
    if collection is None:
        raise NotFound("That collection no longer exists.")
    items = services.collections.pins(collection.id)
    if c.query.get("format") == "docx":
        return _download(export.to_docx(collection.name, items), f"{collection.name}.docx",
                         "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    return _download(export.to_markdown(collection.name, items), f"{collection.name}.md", "text/markdown; charset=utf-8")


# ---- Edition comparison -------------------------------------------------------------------------

def _clause(clause) -> Optional[dict]:
    return None if clause is None else {"num": clause.num, "title": clause.title, "page": clause.page,
                                        "bbox": clause.bbox, "text": clause.text}


@api("GET", "/compare")
def compare_editions(c: Call) -> Any:
    old, new = services.document(int(c.query.get("old", 0))), services.document(int(c.query.get("new", 0)))
    if old.id == new.id:
        raise ValueError("Choose two different documents.")
    diffs = services.comparison(old, new)
    name = f"{old.title} vs {new.title}"
    if c.query.get("format") == "md":
        return _download(to_markdown(old.title, new.title, diffs), f"{name}.md", "text/markdown; charset=utf-8")
    if c.query.get("format") == "csv":
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["Status", "Renumbered", "Old clause", "Old title", "New clause", "New title", "Similarity",
                         "Provision change"])
        for d in diffs:
            writer.writerow([d.status, d.renumbered, d.old.num if d.old else "", d.old.title if d.old else "",
                             d.new.num if d.new else "", d.new.title if d.new else "", round(d.similarity, 3),
                             provision_change(d)])
        return _download(out.getvalue(), f"{name}.csv", "text/csv; charset=utf-8")
    return {
        "counts": {s: sum(d.status == s for d in diffs) for s in ("changed", "added", "removed", "unchanged")},
        "renumbered": sum(d.renumbered for d in diffs),
        "provision_changes": sum(d.provisions_changed for d in diffs),
        "diffs": [{"status": d.status, "renumbered": d.renumbered, "similarity": d.similarity,
                   "provision_change": provision_change(d), "old": _clause(d.old), "new": _clause(d.new),
                   "html": word_diff_html(d.old.text, d.new.text)
                   if d.status == "changed" and d.old.text != d.new.text else None} for d in diffs],
    }


# ---- Source code --------------------------------------------------------------------------------

def _codebase(codebase_id: int):
    codebase = services.code.get(codebase_id)
    if codebase is None:
        raise NotFound("That codebase is no longer in the list.")
    return codebase


def _symbol(symbol_id: int):
    symbol = services.code.symbol(symbol_id)
    if symbol is None:
        raise NotFound("That symbol is no longer in the code index (the codebase was rescanned).")
    return symbol


@api("POST", "/codebases")
def add_codebase(c: Call) -> dict:
    codebase = services.code.add(str(c.data.get("root", "")), str(c.data.get("name", "")))
    services.indexer.submit(CODE, codebase.name, doc_id=codebase.id)
    return plain(codebase)


@api("DELETE", "/codebases/{id:int}")
def remove_codebase(c: Call) -> dict:
    if c.path["id"] in services.indexer.pending_codebases():
        raise ValueError("That codebase is being scanned; remove it when that's done.")
    services.code.remove(c.path["id"])
    return {"removed": True}


@api("POST", "/codebases/{id:int}/scan")
def scan_codebase(c: Call) -> dict:
    codebase = _codebase(c.path["id"])
    if codebase.id in services.indexer.pending_codebases():
        raise ValueError("That codebase is already being scanned.")
    return _job(services.indexer.submit(CODE, codebase.name, doc_id=codebase.id))


@api("GET", "/codebases/{id:int}/files")
def code_files(c: Call) -> list:
    return services.code.files(_codebase(c.path["id"]).id)


@api("GET", "/codebases/{id:int}/symbols")
def code_symbols(c: Call) -> list:
    return services.code.search_symbols(_codebase(c.path["id"]).id, c.query.get("q", ""), c.words("kinds") or None)


@api("GET", "/codebases/{id:int}/text")
def code_text(c: Call) -> list:
    hits = services.code.search_text(_codebase(c.path["id"]).id, c.query.get("q", ""))
    return [{"file_id": f.id, "path": f.path, "line": line, "text": text.strip()[:240]} for f, line, text in hits]


@api("GET", "/code/files/{id:int}")
def code_file(c: Call) -> dict:
    code = services.code
    file = code.file(c.path["id"])
    if file is None:
        raise NotFound("That file is no longer in the code index.")
    return {"file": file, "text": "\n".join(code.lines(file.id)), "outline": code.outline(file.id),
            "imports": code.imports_of(file.id), "imported_by": code.imported_by(file.id)}


@api("GET", "/code/files/{id:int}/at")
def code_at(c: Call) -> dict:
    """What's written at a position: the reference there and what it points to, or the symbol declared there."""
    code = services.code
    file = code.file(c.path["id"])
    if file is None:
        raise NotFound("That file is no longer in the code index.")
    line, col = int(c.query.get("line", 1)), int(c.query.get("col", 1))
    ref: Optional[Usage] = code.ref_at(file.id, line, col)
    target = code.symbol(ref.target_id) if ref else None
    unlinked = ref is not None and target is None and not ref.target
    return {"ref": ref, "target": target, "declared": code.declared_at(file.id, line, col),
            "candidates": code.named(file.codebase_id, ref, file.language == JAVA) if unlinked else []}


@api("GET", "/code/symbols/{id:int}")
def code_symbol(c: Call) -> dict:
    symbol = _symbol(c.path["id"])
    return {"symbol": symbol, "members": services.code.members(symbol.id), "hierarchy": services.code.hierarchy(symbol)}


@api("GET", "/code/symbols/{id:int}/usages")
def code_usages(c: Call) -> list:
    return services.code.usages(_symbol(c.path["id"]))


@api("GET", "/code/symbols/{id:int}/calls")
def code_calls(c: Call) -> dict:
    """The caller or callee tree (certain links only), with calls to outside APIs and calls that couldn't be linked."""
    code, symbol = services.code, _symbol(c.path["id"])
    callers = c.query.get("direction", "callers") == "callers"
    loose = [u for u in (code.callers(symbol) if callers else code.callees(symbol))
             if (u.certainty != "resolved" if callers else u.target_id is None)]
    return {"tree": code.call_tree(symbol, callers=callers), "depth": config.CODE_CALL_DEPTH,
            "outside": [u for u in loose if u.target], "unlinked": [u for u in loose if not u.target]}


@api("GET", "/codebases/{id:int}/dependencies")
def code_dependencies(c: Call) -> dict:
    code, codebase = services.code, _codebase(c.path["id"])
    return {"declared": code.declared(codebase.id),
            "packages": [{"name": n, "files": f, "uses": u} for n, f, u in code.external_packages(codebase.id)],
            "internal": [{"source": a, "target": b, "references": n} for a, b, n in code.internal_dependencies(codebase.id)]}


@api("GET", "/codebases/{id:int}/package")
def code_package(c: Call) -> dict:
    code, codebase, name = services.code, _codebase(c.path["id"]), c.query.get("name", "")
    return {"members": [{"name": n, "uses": u} for n, u in code.external_members(codebase.id, name)],
            "imports": code.package_imports(codebase.id, name)}


@api("GET", "/codebases/{id:int}/external")
def code_external_usages(c: Call) -> list:
    return services.code.external_usages(_codebase(c.path["id"]).id, c.query.get("target", ""))


@api("GET", "/codebases/{id:int}/links")
def code_package_links(c: Call) -> list:
    return services.code.package_links(_codebase(c.path["id"]).id, c.query.get("source", ""), c.query.get("target", ""))


@api("GET", "/codebases/{id:int}/endpoints")
def code_endpoints(c: Call) -> dict:
    served, unmatched = services.code.endpoints(_codebase(c.path["id"]).id)
    return {"served": [{"route": route, "calls": calls} for route, calls in served], "unmatched": unmatched}


# ---- The app ------------------------------------------------------------------------------------

class _Headers(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Content-Security-Policy", _CONTENT_SECURITY)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response


async def _not_built(request: Request) -> Response:
    return PlainTextResponse("The front end hasn't been built. Run: cd web && npm ci && npm run build", status_code=503)


def create_app() -> Starlette:
    front = [Mount("/", StaticFiles(directory=STATIC, html=True))] if (STATIC / "index.html").exists() \
        else [Route("/", _not_built)]
    return Starlette(routes=[*_routes, *front], middleware=[Middleware(_Headers)])


app = create_app()
