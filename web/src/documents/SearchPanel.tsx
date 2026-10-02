import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { api, query as queryString } from "../api";
import { useLoad } from "../hooks";
import { Highlight, useApp } from "../store";
import { Block, IdentifierResults, SearchResult } from "../types";
import { Badge, Chips, Empty, Marked, saveText, Segments, Status, Table, tableToCsv } from "../ui";
import { ResultCard } from "./ResultCard";

interface Submitted { text: string; identifier: boolean; children: boolean }

/** Search the documents by words and meaning, or by identifier; results open in the page view. */
export function SearchPanel() {
  const app = useApp();
  const { overview } = app;
  const [text, setText] = useState("");
  const [identifier, setIdentifier] = useState(false);
  const [children, setChildren] = useState(false);
  const [submitted, setSubmitted] = useState<Submitted | null>(null);
  const [docs, setDocs] = useState<number[]>([]);
  const [content, setContent] = useState<string[]>([]);
  const [provisions, setProvisions] = useState<string[]>([]);
  const [order, setOrder] = useState<"Relevance" | "Position">("Relevance");
  const [limit, setLimit] = useState(overview.max_results);
  const [selected, setSelected] = useState(0);
  const [trail, setTrail] = useState<string[]>([]);    // Identifiers followed, to step back along
  const opened = useRef("");

  const scope = useMemo(() => ({
    docs,
    kinds: content.flatMap((name) => overview.content_kinds[name] ?? []),
    provisions: provisions.map((name) => overview.provisions[name]),
  }), [docs, content, provisions, overview.content_kinds, overview.provisions]);

  const words = useLoad<{ total: number; by_meaning: boolean; results: SearchResult[] }>(
    () => (submitted && !submitted.identifier
      ? api.get(`/search` + queryString({ q: submitted.text, ...scope, order: order === "Position" ? "document" : undefined, limit }))
      : null),
    [submitted, scope, order, limit]);
  const ids = useLoad<IdentifierResults>(
    () => (submitted?.identifier ? api.get(`/identifiers` + queryString({ q: submitted.text, children: submitted.children, ...scope })) : null),
    [submitted, scope]);

  const highlight: Highlight = useMemo(() => (!submitted ? {} : submitted.identifier
    ? { identifier: submitted.text, children: submitted.children } : { q: submitted.text }), [submitted]);
  const blocks: Block[] = useMemo(
    () => (submitted?.identifier ? ids.data?.hits.map((h) => h.block) : words.data?.results.map((r) => r.block)) ?? [],
    [submitted, ids.data, words.data]);

  const open = (index: number) => {
    const block = blocks[index];
    if (!block || block.doc_id === null) return;
    setSelected(index);
    app.openDoc({ docId: block.doc_id, page: block.page, target: block.bbox, blockId: block.id, highlight });
  };

  // A new search shows its first result straight away
  useEffect(() => {
    const key = JSON.stringify([submitted, scope, order, limit]);
    if (blocks.length && opened.current !== key && !words.loading && !ids.loading) {
      opened.current = key;
      open(0);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [blocks]);

  // Alt+Up / Alt+Down step through the results while the page view keeps the focus
  useEffect(() => {
    if (app.activity !== "search") return;
    const onKey = (event: KeyboardEvent) => {
      if (!event.altKey || (event.key !== "ArrowUp" && event.key !== "ArrowDown")) return;
      event.preventDefault();
      open(Math.min(Math.max(selected + (event.key === "ArrowDown" ? 1 : -1), 0), blocks.length - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [app.activity, selected, blocks]);

  const search = (value: string, asIdentifier = identifier, extendTrail = false) => {
    const trimmed = value.trim();
    setText(trimmed);
    setIdentifier(asIdentifier);
    setSubmitted(trimmed ? { text: trimmed, identifier: asIdentifier, children } : null);
    if (asIdentifier && trimmed) setTrail((t) => (extendTrail ? [...t, trimmed] : [trimmed]));
    app.refresh();
  };
  const submit = (event: FormEvent) => { event.preventDefault(); search(text); };

  const download = () => {
    const rows = submitted?.identifier
      ? ids.data!.hits.map((h, i) => [String(i + 1), h.doc_title, h.block.clause, h.block.display_page, ids.data!.groups[h.group], h.block.text, h.citation])
      : words.data!.results.map((r, i) => [String(i + 1), r.doc_title, r.block.clause, r.block.display_page, r.match, r.block.text, r.citation]);
    saveText("search_results.csv", tableToCsv({ columns: ["Rank", "Document", "Clause", "Page", "Match", "Text", "Citation"], rows }));
  };

  const filtered = docs.length + content.length + provisions.length > 0;
  return (
    <div className="panel">
      <form className="panel-head" onSubmit={submit}>
        <div className="row">
          <input className="grow" type="search" value={text} onChange={(e) => setText(e.target.value)} aria-label="Search the library"
                 placeholder={identifier ? "An identifier: a message label, field, part number…" : 'Words, a question, or "an exact phrase"'} />
          <button className="primary" type="submit">Search</button>
        </div>
        <div className="row wrap">
          <label className="check" title="Look up an identifier exactly, grouped by role, with related identifiers">
            <input type="checkbox" checked={identifier} onChange={(e) => { setIdentifier(e.target.checked); setSubmitted(null); }} /> Identifier
          </label>
          {identifier && (
            <label className="check" title="Also match identifiers that extend this one (K3.5 → K3.5C1)">
              <input type="checkbox" checked={children} onChange={(e) => { setChildren(e.target.checked); setSubmitted(null); }} /> Include sub-identifiers
            </label>
          )}
          <details className="help">
            <summary>Syntax</summary>
            {identifier ? (
              <p>Case, spaces and hyphens are ignored: <code>K3.5</code>, <code>k 3.5</code> and <code>k-3.5</code> are the
                same identifier. Results are grouped: headings and captions (where it's introduced), table rows, rules
                (shall / should / may), then other mentions.</p>
            ) : (
              <p>Plain words and questions also match passages that say the same thing in other words (marked
                <em> meaning</em>). <code>"shall not exceed"</code> finds the exact phrase; <code>pump OR compressor</code> either
                word; <code>valve -relief</code> excludes a word; <code>calib*</code> matches a prefix. Using any of these
                searches for exactly those words.</p>
            )}
          </details>
        </div>
        <details className="scope" open={filtered}>
          <summary>Scope{filtered ? " (filtered)" : ""}</summary>
          <div className="field">
            <span>Documents</span>
            <div className="doc-list">
              {overview.documents.map((d) => (
                <label key={d.id} className="check">
                  <input type="checkbox" checked={docs.includes(d.id)}
                         onChange={(e) => setDocs(e.target.checked ? [...docs, d.id] : docs.filter((id) => id !== d.id))} /> {d.title}
                </label>
              ))}
              {!docs.length && <span className="muted">All documents</span>}
            </div>
          </div>
          <div className="field"><span>Content</span>
            <Chips options={Object.keys(overview.content_kinds)} value={content} onChange={setContent} /></div>
          <div className="field"><span title="Classified by verbal form: shall, should, may; NOTE/EXAMPLE are informative">Provisions</span>
            <Chips options={Object.keys(overview.provisions)} value={provisions} onChange={setProvisions} /></div>
          <div className="field"><span>Order</span>
            <Segments options={["Relevance", "Position"] as const} value={order} onChange={setOrder}
                      labels={{ Position: "Position in document" }} /></div>
          <div className="field"><span>Max results</span>
            <input type="number" min={5} max={100} step={5} value={limit} onChange={(e) => setLimit(Number(e.target.value) || 25)} /></div>
        </details>
      </form>

      <div className="panel-body">
        {!submitted && (
          overview.documents.length === 0
            ? <Empty>The library is empty. Add PDFs in <strong>Library</strong> to start searching.</Empty>
            : (
              <div className="recent">
                <div className="group-title">Recent searches</div>
                {overview.recent.map((q) => <button key={q} type="button" className="link" onClick={() => search(q, false)}>{q}</button>)}
                {!overview.recent.length && <span className="muted">None yet.</span>}
              </div>
            )
        )}
        <Status loading={words.loading || ids.loading} error={words.error || ids.error} />

        {submitted && !submitted.identifier && words.data && (
          <>
            <div className="summary">
              <span>Showing <strong>{words.data.results.length}</strong> of <strong>{words.data.total}</strong> matching passages</span>
              {words.data.results.length > 0 && <button type="button" className="link" onClick={download}>CSV</button>}
            </div>
            {!words.data.results.length && (
              <div className="notice">No passages match. Try fewer words, a prefix like <code>calib*</code>, OR between
                alternatives, or fewer filters.</div>
            )}
            {words.data.results.map((r, i) => (
              <ResultCard key={r.block.id} block={r.block} docTitle={r.doc_title} selected={i === selected} onOpen={() => open(i)}
                          terms={r.terms} pinQuery={submitted.text}
                          extraBadges={r.match === "meaning" && <Badge kind="meaning" title="Found by meaning: it doesn't contain all your search words">meaning</Badge>}
                          detail={<>{matchText(r)} · {r.citation}</>}>
                {r.table ? <Table table={r.table} /> : <div dangerouslySetInnerHTML={{ __html: r.html }} />}
              </ResultCard>
            ))}
          </>
        )}

        {submitted?.identifier && ids.data && (
          <IdentifierResultsView data={ids.data} text={submitted.text} trail={trail} selected={selected} onOpen={open}
                                 onFollow={(value) => search(value, true, true)}
                                 onBack={() => { const earlier = trail.slice(0, -1); search(earlier[earlier.length - 1], true); setTrail(earlier); }}
                                 onDownload={download} />
        )}
      </div>
    </div>
  );
}

function matchText(r: SearchResult): string {
  if (r.match === "meaning") return `Matched by meaning (${(r.similarity ?? 0).toFixed(2)})`;
  if (r.match === "both") return "Matched by words and meaning";
  if (r.match === "some") return "Contains some of the words";
  return `Score ${r.score.toFixed(2)}`;
}

function IdentifierResultsView({ data, text, trail, selected, onOpen, onFollow, onBack, onDownload }: {
  data: IdentifierResults; text: string; trail: string[]; selected: number; onOpen: (index: number) => void;
  onFollow: (value: string) => void; onBack: () => void; onDownload: () => void;
}) {
  const { related } = data;
  const groups: [string, { value: string; why: string }[]][] = [];
  if (related.parent) groups.push(["Part of", [{ value: related.parent, why: "The identifier this one extends" }]]);
  if (related.children.length) groups.push(["Sub-identifiers", related.children.map((value) => ({ value, why: "Extends this identifier" }))]);
  if (related.related.length) {
    groups.push(["Related", related.related.map((r) => ({
      value: r.value, why: `Shares ${r.same_row} table row${r.same_row === 1 ? "" : "s"} and ${r.same_passage} passage${r.same_passage === 1 ? "" : "s"}`,
    }))]);
  }
  return (
    <>
      <div className="id-panel">
        <div className="row">
          <strong className="grow">{trail.join(" → ") || text}</strong>
          <button type="button" disabled={trail.length < 2} onClick={onBack} title="Return to the previous identifier on the trail">Back</button>
        </div>
        {groups.map(([title, items]) => (
          <div key={title} className="row wrap">
            <span className="muted">{title}</span>
            {items.map((item) => <button key={item.value} type="button" className="link" title={item.why} onClick={() => onFollow(item.value)}>{item.value}</button>)}
          </div>
        ))}
        {!groups.length && <span className="muted">No related identifiers found. Only switched-on identifier patterns are used (Library → a document's identifiers).</span>}
      </div>
      {data.outdated > 0 && (
        <div className="notice">{data.outdated} document(s) in scope were indexed by an older version and may miss identifiers. Re-index them in Library.</div>
      )}
      <div className="summary">
        <span><strong>{text}</strong> appears in <strong>{data.hits.length}</strong> passage{data.hits.length === 1 ? "" : "s"}</span>
        {data.hits.length > 0 && <button type="button" className="link" onClick={onDownload}>CSV</button>}
      </div>
      {!data.hits.length && (
        <div className="notice">
          No passages contain the identifier “{text}” in the current scope.
          {data.suggestions.length > 0 && (
            <div className="row wrap"><span className="muted">Did you mean</span>
              {data.suggestions.map((s) => <button key={s} type="button" className="link" onClick={() => onFollow(s)}>{s}</button>)}</div>
          )}
        </div>
      )}
      {data.hits.map((hit, i) => (
        <div key={hit.block.id}>
          {(i === 0 || data.hits[i - 1].group !== hit.group) && (
            <div className="group-title">{data.groups[hit.group]} · {data.hits.filter((h) => h.group === hit.group).length}</div>
          )}
          <ResultCard block={hit.block} docTitle={hit.doc_title} selected={i === selected} onOpen={() => onOpen(i)}
                      pinQuery={text} detail={<>{data.groups[hit.group]} · {hit.citation}</>}>
            {hit.table ? <Table table={hit.table} highlight={hit.values} /> : <Marked text={hit.block.text} values={hit.values} />}
          </ResultCard>
        </div>
      ))}
    </>
  );
}
