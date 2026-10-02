"""
Code browsing: a Java / JavaScript / TypeScript codebase read the way an IDE lets you, to trace code
paths and see how the parts depend on each other.

The sidebar's Code tab (beside the documents' Search Scope) chooses the codebase and what is searched
for; while it's open, the main area is the code browser. Its left pane switches between Search (symbols or text), Symbol (the symbol being explored: its
usages, callers and callees, hierarchy), Dependencies (libraries and packages), APIs (HTTP routes and
the calls that reach them) and Files. The right pane shows the source, with the line in question
highlighted. Everything followed is added to a trail, so a code path can be retraced.
"""
import html
from typing import Dict, Optional, Sequence

import pandas as pd
import streamlit as st
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

from src import config
from src.code.models import BY_NAME, RESOLVED, SUPERTYPE, CallNode, Codebase, Symbol, Usage
from src.code.store import CodeStore
from src.models import TextBlock
from src.research.collections import CollectionStore
from src.search.indexer import CODE, Indexer

SEARCH, SYMBOL, DEPENDENCIES, APIS, FILES = "Search", "Symbol", "Dependencies", "APIs", "Files"
_VIEWS = [SEARCH, SYMBOL, DEPENDENCIES, APIS, FILES]
_LISTED = 100           # Rows drawn per list: each is a button, and a page of them is plenty to read
_KIND_FILTERS = {"Types": ("class", "interface", "enum", "record", "annotation", "type"),
                 "Methods & functions": ("method", "constructor", "function"),
                 "Fields & variables": ("field", "variable")}
_CERTAINTY = {RESOLVED: "Linked", SUPERTYPE: "Through a supertype", BY_NAME: "By name only"}
_CERTAINTY_HELP = {
    RESOLVED: "Followed through imports, declared types or scope.",
    SUPERTYPE: "Calls made through an interface or superclass method that this one implements or overrides.",
    BY_NAME: "The name (and number of arguments) agrees, but what it's called on couldn't be told without "
             "compiling the code. Check these before relying on them.",
}
_LEXERS = {"java": "java", "javascript": "jsx", "typescript": "tsx"}


# ---- State ------------------------------------------------------------------------------------------
# "code_file"/"code_line": what the viewer shows; "code_symbol": the symbol being explored;
# "code_trail": symbols followed to get here; "code_view": the left pane's view.

def open_location(file_id: int, line: int) -> None:
    st.session_state["code_file"], st.session_state["code_line"] = file_id, line
    st.session_state["code_line_input"] = line


def explore(symbol_id: int, file_id: int, line: int, restart: bool = False) -> None:
    """Shows a symbol's declaration and explores from it; `restart` begins a new trail."""
    trail = [] if restart else st.session_state.get("code_trail", [])
    if symbol_id in trail:
        trail = trail[:trail.index(symbol_id)]   # Back to an earlier step: drop what followed
    st.session_state["code_trail"] = [*trail, symbol_id][-12:]
    st.session_state["code_symbol"] = symbol_id
    open_location(file_id, line)
    _set_view(SYMBOL)


def _set_view(view: str) -> None:
    st.session_state["code_view"] = view
    st.session_state["code_view_input"] = view


def _jump() -> None:
    st.session_state["code_line"] = st.session_state["code_line_input"]


def _reset(codebase_id: Optional[int] = None) -> None:
    for key in ("code_file", "code_line", "code_symbol", "code_trail", "code_line_input"):
        st.session_state.pop(key, None)
    st.session_state["code_base"] = codebase_id


# ---- Entry point ------------------------------------------------------------------------------------

def render_code_sidebar(store: CodeStore, indexer: Indexer) -> Optional[Codebase]:
    """
    The sidebar's Code tab, the counterpart of the documents' Search Scope: which codebase is searched,
    what the search looks for, and adding, rescanning or removing codebases. Returns the chosen codebase.
    """
    st.header("Code Search")
    codebases = store.list_codebases()
    if not codebases:
        st.caption("No codebase yet. Add the top folder of a Java, JavaScript or TypeScript project.")
        _add_form(store, indexer)
        return None

    current = next((c for c in codebases if c.id == st.session_state.get("code_base")), codebases[0])
    chosen = st.selectbox("Codebase", codebases, index=codebases.index(current), format_func=lambda c: c.name)
    if chosen.id != st.session_state.get("code_base"):
        _reset(chosen.id)
        if chosen.id != current.id:
            st.rerun()
    scanning = current.id in indexer.pending_codebases()
    if current.indexed_at:
        st.caption(f"{current.file_count:,} files · {current.symbol_count:,} symbols · scanned "
                   f"{current.indexed_at.replace('T', ' ')}" + (" · rescanning now" if scanning else ""),
                   help=current.root)

    mode = st.radio("Search for", ["Symbols", "Text"], horizontal=True, key="code_search_mode",
                    help="Symbols: classes, methods, functions and fields by name. Text: any piece of the "
                         "source, such as a string, a URL or part of an identifier.")
    if mode == "Symbols":
        st.pills("Kinds", list(_KIND_FILTERS), selection_mode="multi", key="code_kinds",
                 help="Nothing selected searches every kind of symbol")

    st.button("Rescan", icon=":material/refresh:", disabled=scanning, on_click=indexer.submit,
              args=(CODE, current.name), kwargs={"doc_id": current.id}, width="stretch",
              help="Read new and changed files again (runs in the background)")
    with st.popover("Add codebase", icon=":material/add:", width="stretch"):
        _add_form(store, indexer)
    with st.popover("Remove…", disabled=scanning, width="stretch"):
        st.write(f"Forget **{current.name}** and its index? The folder itself isn't touched.")
        if st.button("Remove from the app", type="primary"):
            store.remove(current.id)
            _reset()
            st.rerun()
    return current


def render_code_browser(store: CodeStore, indexer: Indexer, collections: CollectionStore, collection_id: int,
                        current: Optional[Codebase]) -> None:
    """The main area while the sidebar's Code tab is open: the chosen codebase's views beside the source viewer."""
    if current is None:
        st.info("Add a folder of Java, JavaScript or TypeScript source in the sidebar to browse it: find where "
                "anything is declared and used, follow calls, and see which libraries and APIs the code depends on. "
                "The folder is read where it is; nothing in it is changed.")
        return
    if not current.indexed_at:
        st.info(f"**{current.name}** is being read for the first time; progress is in the sidebar. "
                "It appears here when that's done." if current.id in indexer.pending_codebases() else
                f"**{current.name}** hasn't been scanned yet. Use **Rescan** in the sidebar.")
        return

    left, right = st.columns([2, 3], gap="medium")
    with left:
        if "code_view_input" not in st.session_state:   # Widget state is discarded while the tab isn't drawn
            st.session_state["code_view_input"] = st.session_state.get("code_view", SEARCH)
        view = st.segmented_control("View", _VIEWS, key="code_view_input", label_visibility="collapsed",
                                    width="stretch") or SEARCH
        st.session_state["code_view"] = view
        {SEARCH: _search_view, SYMBOL: _symbol_view, DEPENDENCIES: _dependencies_view, APIS: _apis_view,
         FILES: _files_view}[view](store, current, _Pinner(collections, collection_id, current))
    with right:
        with st.container(border=True):
            _viewer(store)


def _add_form(store: CodeStore, indexer: Indexer) -> None:
    with st.form("add_codebase", clear_on_submit=True, border=False):
        root = st.text_input("Folder", placeholder=r"C:\Projects\my-app  or  /Users/me/projects/my-app",
                             help="The top folder of the source code, on the machine this app runs on")
        name = st.text_input("Name (optional)", placeholder="Defaults to the folder's name")
        if st.form_submit_button("Add and scan", type="primary"):
            try:
                codebase = store.add(root, name)
            except ValueError as e:
                st.error(str(e))
            else:
                indexer.submit(CODE, codebase.name, doc_id=codebase.id)
                _reset(codebase.id)
                st.rerun()


class _Pinner:
    """Pins a piece of source to the active collection, with where it came from."""

    def __init__(self, collections: CollectionStore, collection_id: int, codebase: Codebase):
        self.collections, self.collection_id, self.codebase = collections, collection_id, codebase

    def pin(self, path: str, line: int, text: str, label: str) -> None:
        block = TextBlock(id=0, page=line, text=text, word_count=len(text.split()), page_label=str(line), kind="code",
                          label=f"{path}:{line}", clause_title=label)
        self.collections.add_pin(self.collection_id, block, self.codebase.name,
                                 f"{self.codebase.name}, {path}:{line}", query=label)
        st.toast(f"Pinned {path}:{line}")


# ---- Shared pieces ----------------------------------------------------------------------------------

def _short(path: str, parts: int = 3) -> str:
    pieces = path.split("/")
    return "/".join(pieces[-parts:]) if len(pieces) > parts else path


def _symbol_row(symbol: Symbol, key: str, restart: bool = False, prefix: str = "", note: str = "") -> None:
    """A symbol to click: explores it and shows its declaration."""
    st.button(f"{prefix}{symbol.qualified}", key=key, type="tertiary", on_click=explore,
              args=(symbol.id, symbol.file_id, symbol.line, restart),
              help=f"{symbol.kind} · {symbol.location}" + (f" · {note}" if note else ""))


def _usage_rows(usages: Sequence[Usage], key: str, show_target: bool = False) -> None:
    """Places in the code, each opening its line; the enclosing symbol can be explored from there."""
    for i, usage in enumerate(usages[:_LISTED]):
        with st.container(horizontal=True, wrap=False, vertical_alignment="center", gap="small"):
            st.button(f"{_short(usage.path)}:{usage.line}", key=f"{key}_{i}", type="tertiary", on_click=open_location,
                      args=(usage.file_id, usage.line), help=f"{usage.path} · in {usage.from_name or 'the file'}")
            target = f' <span class="code-target">→ {html.escape(usage.target)}</span>' if show_target and usage.target else ""
            st.html(f'<code class="code-line">{html.escape(usage.text[:160])}</code>{target}', width="stretch")
    if len(usages) > _LISTED:
        st.caption(f"Showing the first {_LISTED} of {len(usages)}.")


# ---- Search -----------------------------------------------------------------------------------------

def _search_view(store: CodeStore, codebase: Codebase, pinner: _Pinner) -> None:
    mode = st.session_state.get("code_search_mode", "Symbols")   # Chosen in the sidebar, with the kinds
    query = st.text_input("Search the code", key="code_query", label_visibility="collapsed",
                          placeholder="A class, method or function name" if mode == "Symbols" else "Any text in the source")
    if not query.strip():
        st.caption("Results open in the viewer; choosing a symbol explores its usages, calls and hierarchy. "
                   "The sidebar chooses the codebase and whether symbols or text are searched.")
        return
    with st.container(height=config.RESULTS_PANE_HEIGHT, border=False):
        if mode == "Symbols":
            kinds = [k for g in st.session_state.get("code_kinds") or [] for k in _KIND_FILTERS[g]] or None
            symbols = store.search_symbols(codebase.id, query, kinds)
            st.caption(f"{len(symbols)} symbol{'s' if len(symbols) != 1 else ''}"
                       + (f" (the first {config.CODE_MAX_RESULTS})" if len(symbols) >= config.CODE_MAX_RESULTS else ""))
            for i, symbol in enumerate(symbols[:_LISTED]):
                with st.container(border=True):
                    st.html(f'<div class="result-head"><span class="badge badge-object">{html.escape(symbol.kind)}</span>'
                            f'<span class="result-doc">{html.escape(symbol.name)}</span></div>'
                            f'<div class="result-path">{html.escape(symbol.location)}</div>'
                            f'<code class="code-line">{html.escape(symbol.signature)}</code>')
                    st.button("Explore", key=f"code_hit_{i}", on_click=explore,
                              args=(symbol.id, symbol.file_id, symbol.line, True), width="content")
        else:
            hits = store.search_text(codebase.id, query)
            st.caption(f"{len(hits)} line{'s' if len(hits) != 1 else ''}"
                       + (f" (the first {config.CODE_MAX_RESULTS})" if len(hits) >= config.CODE_MAX_RESULTS else ""))
            for i, (file, line, text) in enumerate(hits[:_LISTED]):
                with st.container(horizontal=True, wrap=False, vertical_alignment="center", gap="small"):
                    st.button(f"{_short(file.path)}:{line}", key=f"code_text_{i}", type="tertiary",
                              on_click=open_location, args=(file.id, line), help=file.path)
                    st.html(f'<code class="code-line">{html.escape(text.strip()[:160])}</code>', width="stretch")


# ---- Symbol -----------------------------------------------------------------------------------------

def _symbol_view(store: CodeStore, codebase: Codebase, pinner: _Pinner) -> None:
    symbol = store.symbol(st.session_state.get("code_symbol"))
    if symbol is None:
        st.info("Choose a symbol from **Search**, or from the viewer's Outline, to explore where it's used, "
                "what calls it, what it calls, and its type hierarchy.")
        return

    trail = [s for s in (store.symbol(i) for i in st.session_state.get("code_trail", [])) if s]
    if len(trail) > 1:
        with st.container(horizontal=True, wrap=True, vertical_alignment="center", gap="small"):
            for i, step in enumerate(trail):
                if i:
                    st.html('<span class="trail-sep">›</span>', width="content")
                st.button(step.name, key=f"code_trail_{i}", type="tertiary", disabled=step.id == symbol.id,
                          on_click=explore, args=(step.id, step.file_id, step.line), help=step.qualified)

    with st.container(horizontal=True, vertical_alignment="center"):
        st.html(f'<div class="result-head"><span class="badge badge-object">{html.escape(symbol.kind)}</span>'
                f'<span class="result-doc">{html.escape(symbol.qualified)}</span></div>'
                f'<div class="result-path">{html.escape(symbol.location)}</div>', width="stretch")
        body = "\n".join(store.lines(symbol.file_id)[symbol.line - 1:symbol.end_line][:60])
        st.button("Pin", icon=":material/push_pin:", key="code_pin", on_click=pinner.pin,
                  args=(symbol.path, symbol.line, body, symbol.qualified), help="Save its source to the active collection")
        st.button("Show", key="code_show", on_click=open_location, args=(symbol.file_id, symbol.line),
                  help="Show its declaration in the viewer")
    st.html(f'<code class="code-line">{html.escape(symbol.signature)}</code>')

    names = ["Usages", "Calls", "Hierarchy"] + (["Members"] if symbol.is_type or symbol.kind == "variable" else [])
    tabs = dict(zip(names, st.tabs(names)))
    with tabs["Usages"]:
        _usages(store, symbol)
    with tabs["Calls"]:
        _calls(store, symbol)
    with tabs["Hierarchy"]:
        _hierarchy(store, symbol)
    if "Members" in tabs:
        with tabs["Members"]:
            for i, member in enumerate(store.members(symbol.id)):
                _symbol_row(member, f"code_member_{i}", note=member.signature)


def _usages(store: CodeStore, symbol: Symbol) -> None:
    usages = store.usages(symbol)
    if not usages:
        st.caption("No references to it were found in this codebase.")
        return
    with st.container(height=config.RESULTS_PANE_HEIGHT - 260, border=False):
        for certainty, title in _CERTAINTY.items():
            group = [u for u in usages if u.certainty == certainty]
            if group:
                st.html(f'<div class="related-group" title="{html.escape(_CERTAINTY_HELP[certainty])}">'
                        f'{title} · {len(group)}</div>')
                if certainty == BY_NAME:
                    st.caption(_CERTAINTY_HELP[BY_NAME])
                _usage_rows(group, f"code_use_{certainty}")


def _tree(nodes: Sequence[CallNode], key: str, level: int = 0) -> None:
    for i, node in enumerate(nodes):
        _symbol_row(node.symbol, f"{key}_{level}_{i}_{node.symbol.id}", prefix="\u2003" * level + ("└ " if level else ""),
                    note=f"call at line {node.line}" + (" · more below, not followed" if node.truncated else ""))
        _tree(node.children, f"{key}_{i}", level + 1)


def _calls(store: CodeStore, symbol: Symbol) -> None:
    direction = st.radio("Direction", ["Who calls it", "What it calls"], horizontal=True, key="code_call_direction",
                         label_visibility="collapsed")
    callers = direction == "Who calls it"
    with st.container(height=config.RESULTS_PANE_HEIGHT - 300, border=False):
        tree = store.call_tree(symbol, callers=callers)
        st.html(f'<div class="related-group">{"Callers" if callers else "Calls"}, {config.CODE_CALL_DEPTH} levels deep '
                f'(linked calls only)</div>')
        if tree:
            _tree(tree, "code_tree")
        else:
            st.caption("None that could be linked for certain.")
        loose = [u for u in (store.callers(symbol) if callers else store.callees(symbol))
                 if (u.certainty != RESOLVED if callers else u.target_id is None)]
        outside = [u for u in loose if u.target]
        unknown = [u for u in loose if not u.target]
        if outside:
            st.html(f'<div class="related-group">Calls to outside APIs · {len(outside)}</div>')
            _usage_rows(outside, "code_call_out", show_target=True)
        if unknown:
            title = "Possible callers" if callers else "Calls that couldn't be linked"
            st.html(f'<div class="related-group">{title} · {len(unknown)}</div>')
            _usage_rows(unknown, "code_call_loose")


def _hierarchy(store: CodeStore, symbol: Symbol) -> None:
    found = store.hierarchy(symbol)
    sections = [("Extends / implements", found.supertypes), ("Extended / implemented by", found.subtypes),
                ("Overrides or implements", found.overrides), ("Overridden or implemented by", found.overridden_by)]
    if not any(items for _, items in sections) and not found.external_supertypes:
        st.caption("No supertypes, subtypes or overrides in this codebase.")
    for title, items in sections:
        if items:
            st.html(f'<div class="related-group">{title} · {len(items)}</div>')
            for i, item in enumerate(items[:_LISTED]):
                _symbol_row(item, f"code_h_{title}_{i}")
    if found.external_supertypes:
        st.html('<div class="related-group">Outside supertypes</div>')
        st.html("<br>".join(f"<code>{html.escape(name)}</code>" for name in found.external_supertypes))


# ---- Dependencies -----------------------------------------------------------------------------------

def _selected(frame: pd.DataFrame, key: str) -> Optional[int]:
    """Draws a table whose rows can be picked; returns the picked row's position."""
    event = st.dataframe(frame, hide_index=True, width="stretch", height=280, key=key, on_select="rerun",
                         selection_mode="single-row",
                         column_config={name: st.column_config.TextColumn(width="large")
                                        for name in frame.columns if frame[name].dtype == object})
    rows = event.selection.rows if event and event.selection else []
    return rows[0] if rows else None


def _dependencies_view(store: CodeStore, codebase: Codebase, pinner: _Pinner) -> None:
    libraries, packages, internal = st.tabs(["Declared libraries", "Outside packages used", "Between packages"])
    with libraries:
        declared = store.declared(codebase.id)
        if not declared:
            st.caption("No pom.xml, build.gradle or package.json declares any library.")
        else:
            st.caption("From the build files. For npm, “Files using it” counts the files importing the package: "
                       "0 means it's declared but never imported.")
            st.dataframe(pd.DataFrame([
                {"Library": d.name, "Version": d.version, "Scope": d.scope, "Kind": d.ecosystem,
                 "Files using it": d.used_in, "Declared in": d.manifest} for d in declared
            ]), hide_index=True, width="stretch", height=config.RESULTS_PANE_HEIGHT - 200)
    with packages:
        _outside_packages(store, codebase)
    with internal:
        _between_packages(store, codebase)


def _outside_packages(store: CodeStore, codebase: Codebase) -> None:
    used = store.external_packages(codebase.id)
    if not used:
        st.caption("No imports of outside packages were found.")
        return
    st.caption("Packages imported from outside this codebase. Pick one to see which of its APIs are used, and where.")
    row = _selected(pd.DataFrame(used, columns=["Package", "Files importing it", "Uses of its APIs"]), "code_packages")
    if row is not None:
        package = used[row][0]
        members = store.external_members(codebase.id, package)
        with st.container(height=config.RESULTS_PANE_HEIGHT - 420, border=False):
            if members:
                st.html(f'<div class="related-group">APIs of {html.escape(package)} in use · {len(members)}</div>')
                labels = {f"{name}  ({count})": name for name, count in members[:300]}
                picked = st.selectbox("API", list(labels), key=f"code_member_pick_{package}", label_visibility="collapsed")
                _usage_rows(store.external_usages(codebase.id, labels[picked]), "code_api_use")
            imports = store.package_imports(codebase.id, package)
            st.html(f'<div class="related-group">Imported in · {len(imports)}</div>')
            for i, item in enumerate(imports[:_LISTED]):
                st.button(f"{_short(item['path'])}:{item['line']}  ·  {item['spec']}", key=f"code_imp_{i}",
                          type="tertiary", on_click=open_location, args=(item["file_id"], item["line"]), help=item["path"])


def _between_packages(store: CodeStore, codebase: Codebase) -> None:
    edges = store.internal_dependencies(codebase.id)
    if not edges:
        st.caption("No references between packages (Java) or folders (JavaScript/TypeScript) were linked.")
        return
    st.caption("Which package (or folder) refers to which, by number of linked references. Pick one to see them.")
    row = _selected(pd.DataFrame(edges, columns=["Package", "Depends on", "References"]), "code_edges")
    if row is not None:
        source, target, _ = edges[row]
        with st.container(height=config.RESULTS_PANE_HEIGHT - 420, border=False):
            _usage_rows(store.package_links(codebase.id, source, target), "code_edge_use")


# ---- APIs -------------------------------------------------------------------------------------------

def _apis_view(store: CodeStore, codebase: Codebase, pinner: _Pinner) -> None:
    served, unmatched = store.endpoints(codebase.id)
    if not served and not unmatched:
        st.caption("No HTTP routes (Spring, JAX-RS, Express) or HTTP calls (fetch, axios, $.ajax, http clients) were found.")
        return
    wanted = st.text_input("Filter", key="code_api_filter", placeholder="Part of a path, e.g. /users",
                           label_visibility="collapsed").strip().lower()
    served = [(s, calls) for s, calls in served if wanted in s.path.lower()]
    unmatched = [c for c in unmatched if wanted in c.path.lower()]
    st.caption(f"{len(served)} route{'s' if len(served) != 1 else ''} served · "
               f"{sum(1 for _, calls in served if not calls)} with no caller found here · "
               f"{len(unmatched)} call{'s' if len(unmatched) != 1 else ''} to routes not served here")
    with st.container(height=config.RESULTS_PANE_HEIGHT - 120, border=False):
        for i, (server, calls) in enumerate(served[:_LISTED]):
            with st.container(border=True):
                st.html(f'<div class="result-head"><span class="badge badge-page">{html.escape(server.method)}</span>'
                        f'<span class="result-doc">{html.escape(server.path)}</span>'
                        f'<span class="viewer-count">{html.escape(server.framework)}</span></div>'
                        f'<div class="result-path">{html.escape(server.symbol_name or server.file_path)}</div>')
                with st.container(horizontal=True, wrap=True, vertical_alignment="center", gap="small"):
                    st.button(f"Handler · {_short(server.file_path)}:{server.line}", key=f"code_ep_{i}",
                              on_click=open_location, args=(server.file_id, server.line), width="content")
                    st.caption(f"{len(calls)} caller{'s' if len(calls) != 1 else ''}" if calls else "No caller found in this codebase",
                               width="content")
                for j, call in enumerate(calls):
                    st.button(f"← {call.method} {call.path}  ·  {_short(call.file_path)}:{call.line}", key=f"code_ep_{i}_{j}",
                              type="tertiary", on_click=open_location, args=(call.file_id, call.line),
                              help=f"{call.framework} call in {call.symbol_name or call.file_path}")
        if unmatched:
            st.html(f'<div class="related-group">Calls to routes not served in this codebase · {len(unmatched)}</div>')
            for i, call in enumerate(unmatched[:_LISTED]):
                st.button(f"{call.method} {call.path}  ·  {_short(call.file_path)}:{call.line}", key=f"code_out_{i}",
                          type="tertiary", on_click=open_location, args=(call.file_id, call.line),
                          help=f"{call.framework} call in {call.symbol_name or call.file_path}")


# ---- Files ------------------------------------------------------------------------------------------

def _files_view(store: CodeStore, codebase: Codebase, pinner: _Pinner) -> None:
    files = store.files(codebase.id)
    by_language: Dict[str, int] = {}
    for file in files:
        by_language[file.language] = by_language.get(file.language, 0) + 1
    st.caption(" · ".join(f"{count:,} {language}" for language, count in sorted(by_language.items())))
    current = next((f for f in files if f.id == st.session_state.get("code_file")), None)
    picked = st.selectbox("File", files, index=files.index(current) if current else None, format_func=lambda f: f.path,
                          placeholder="Type part of a path", key=f"code_file_pick_{st.session_state.get('code_file')}")
    if picked is not None and (current is None or picked.id != current.id):
        open_location(picked.id, 1)
        st.rerun()
    broken = [f for f in files if f.has_errors]
    if broken:
        with st.expander(f"{len(broken)} file{'s' if len(broken) != 1 else ''} with syntax the parser couldn't fully read"):
            st.caption("Their symbols are indexed as far as they could be read.")
            for i, file in enumerate(broken[:_LISTED]):
                st.button(file.path, key=f"code_broken_{i}", type="tertiary", on_click=open_location, args=(file.id, 1))


# ---- Viewer -----------------------------------------------------------------------------------------

@st.cache_data(max_entries=64, show_spinner=False)
def _highlighted(text: str, language: str, first: int, marked: tuple) -> str:
    try:
        lexer = get_lexer_by_name(_LEXERS.get(language, language), stripnl=False)
    except ClassNotFound:
        lexer = get_lexer_by_name("text", stripnl=False)
    formatter = HtmlFormatter(noclasses=True, linenos="inline", linenostart=first, hl_lines=list(marked),
                              style="default", nobackground=True, prestyles="margin: 0; font-size: 0.8rem; line-height: 1.5;")
    return highlight(text, lexer, formatter)


def _viewer(store: CodeStore) -> None:
    file = store.file(st.session_state.get("code_file", -1))
    if file is None:
        st.info("Search for a symbol or some text, or pick a file, to see the source here.")
        return
    lines = store.lines(file.id)
    line = min(max(int(st.session_state.get("code_line", 1)), 1), max(len(lines), 1))
    here = store.symbol_at(file.id, line)

    st.html(f'<div class="result-head"><span class="badge badge-page">line {line}</span>'
            f'<span class="result-doc">{html.escape(file.path)}</span>'
            f'<span class="viewer-count">{file.lines:,} lines · {html.escape(file.language)}</span></div>'
            f'<div class="result-path">{html.escape(here.qualified) if here else "&nbsp;"}</div>')
    with st.container(horizontal=True, wrap=True, vertical_alignment="bottom"):
        st.number_input("Go to line", min_value=1, max_value=max(len(lines), 1), step=1, key="code_line_input",
                        on_change=_jump, width=130)
        whole = st.toggle("Whole file", key="code_whole", help="Otherwise the lines around the one in question")
        if here is not None:
            st.button(f"Explore {here.name}", key="code_explore_here", icon=":material/hub:", on_click=explore,
                      args=(here.id, here.file_id, here.line), help=f"Usages, calls and hierarchy of {here.qualified}")

    first = 1 if whole else max(1, line - config.CODE_CONTEXT_LINES)
    last = len(lines) if whole else min(len(lines), line + config.CODE_CONTEXT_LINES)
    code_tab, outline_tab, lines_tab, imports_tab = st.tabs(["Source", "Outline", "On these lines", "Imports"])
    with code_tab:
        st.html(f'<div class="code-frame">{_highlighted(chr(10).join(lines[first - 1:last]), file.language, first, (line - first + 1,))}</div>')
        if not whole and (first > 1 or last < len(lines)):
            st.caption(f"Lines {first}–{last} of {len(lines)}")
    with outline_tab:
        outline = store.outline(file.id)
        if not outline:
            st.caption("No declarations found in this file.")
        depth: Dict[int, int] = {}
        for i, symbol in enumerate(outline[:300]):
            depth[symbol.id] = depth.get(symbol.parent_id, -1) + 1
            st.button("\u2003" * depth[symbol.id] + f"{symbol.name}  ·  {symbol.kind}, line {symbol.line}",
                      key=f"code_outline_{i}", type="tertiary", on_click=explore,
                      args=(symbol.id, symbol.file_id, symbol.line, True), help=symbol.signature)
    with lines_tab:
        _references_here(store, file.id, first, last)
    with imports_tab:
        _imports(store, file.id)


def _references_here(store: CodeStore, file_id: int, first: int, last: int) -> None:
    """What the code on screen refers to, to follow as you would by clicking through in an IDE."""
    refs = store.refs_on_lines(file_id, first, last)
    if not refs:
        st.caption("Nothing on these lines could be linked to a declaration or an outside API.")
        return
    seen = set()
    for i, ref in enumerate(refs):
        key = (ref.line, ref.target_id, ref.target)
        if key in seen:
            continue
        seen.add(key)
        target = store.symbol(ref.target_id)
        if target is not None:
            _symbol_row(target, f"code_here_{i}", prefix=f"{ref.line}:  {ref.name} → ")
        else:
            st.html(f'<div class="code-outside">{ref.line}:&nbsp; {html.escape(ref.name)} → <code>{html.escape(ref.target)}</code> '
                    f'<small>(outside)</small></div>')


def _imports(store: CodeStore, file_id: int) -> None:
    imports = store.imports_of(file_id)
    st.html(f'<div class="related-group">This file imports · {len(imports)}</div>')
    for i, item in enumerate(imports):
        if item["target_file"] is not None:
            st.button(f"{item['spec']}  →  {_short(item['target_path'])}", key=f"code_imports_{i}", type="tertiary",
                      on_click=open_location, args=(item["target_file"], 1), help=item["target_path"])
        else:
            where = f"outside: {item['external']}" if item["external"] else "not found in this codebase"
            st.html(f'<div class="code-outside"><code>{html.escape(item["spec"])}</code> <small>({html.escape(where)})</small></div>')
    importers = store.imported_by(file_id)
    st.html(f'<div class="related-group">Imported by · {len(importers)}</div>')
    for i, item in enumerate(importers[:_LISTED]):
        st.button(f"{_short(item['path'])}:{item['line']}", key=f"code_importer_{i}", type="tertiary",
                  on_click=open_location, args=(item["file_id"], item["line"]), help=item["path"])
