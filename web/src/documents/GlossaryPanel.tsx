import { useEffect, useState } from "react";
import { api } from "../api";
import { useLoad } from "../hooks";
import { useApp } from "../store";
import { Term } from "../types";
import { Empty, Status } from "../ui";

/** Terms and definitions read from a document's "Terms and definitions" clause. */
export function GlossaryPanel() {
  const app = useApp();
  const { documents } = app.overview;
  const [picked, setPicked] = useState<number | null>(null);
  const [filter, setFilter] = useState("");
  const activeDoc = app.active?.kind === "doc" ? app.active.docId : null;
  const [shown, setShown] = useState<number | null>(null);
  useEffect(() => { if (activeDoc !== null) { setShown(activeDoc); setPicked(null); } }, [activeDoc]);
  // The document chosen here; otherwise the one last in view
  const doc = documents.find((d) => d.id === picked) ?? documents.find((d) => d.id === shown) ?? documents[0];
  const docId = doc?.id ?? null;
  const { data, loading, error } = useLoad<Term[]>(
    () => (doc && app.activity === "glossary" ? api.get(`/documents/${doc.id}/glossary`) : null),
    [doc?.id, doc?.block_count, app.activity === "glossary"]);
  const wanted = filter.trim().toLowerCase();
  const terms = (data ?? []).filter((t) => !wanted || [t.term, ...t.synonyms, t.definition].join(" ").toLowerCase().includes(wanted));

  if (!documents.length) return <Empty>Add documents in Library to see their defined terms.</Empty>;
  return (
    <div className="panel">
      <div className="panel-head">
        <select value={docId ?? ""} onChange={(e) => setPicked(Number(e.target.value))} aria-label="Document">
          {documents.map((d) => <option key={d.id} value={d.id}>{d.title}</option>)}
        </select>
        <input type="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter terms and definitions" />
      </div>
      <div className="panel-body">
        <Status loading={loading} error={error} />
        {data && !data.length && <Empty>No “Terms and definitions” clause with numbered entries was found in this document.</Empty>}
        {data && data.length > 0 && <div className="summary"><span>{terms.length} of {data.length} terms</span></div>}
        {terms.map((term) => (
          <article key={term.clause_num + term.term} className="card"
                   onClick={() => app.openDoc({ docId: term.doc_id, page: term.page, target: term.bbox })}>
            <header><span className="card-title">{term.term}</span><span className="muted">{term.clause_num}</span></header>
            {term.synonyms.length > 0 && <div className="card-path">also: {term.synonyms.join(", ")}</div>}
            <div className="card-body">{term.definition}</div>
          </article>
        ))}
      </div>
    </div>
  );
}
