import { useMemo, useState } from "react";
import { api } from "../api";
import { useLoad } from "../hooks";
import { useApp } from "../store";
import { OutlineEntry } from "../types";
import { Empty, Status } from "../ui";

const SHOWN = 1500;   // Entries drawn at once; a filter narrows a longer list

/** The open document's clauses in order: a table of contents to navigate by. */
export function ContentsPanel() {
  const app = useApp();
  const tab = app.active?.kind === "doc" ? app.active : null;
  const doc = app.overview.documents.find((d) => d.id === tab?.docId);
  const [filter, setFilter] = useState("");
  const { data, loading, error } = useLoad<OutlineEntry[]>(
    () => (doc && app.activity === "contents" ? api.get(`/documents/${doc.id}/outline`) : null),
    [doc?.id, doc?.block_count, app.activity === "contents"]);
  const wanted = filter.trim().toLowerCase();
  const entries = useMemo(
    () => (data ?? []).filter((e) => !wanted || `${e.num} ${e.title}`.toLowerCase().includes(wanted)),
    [data, wanted]);
  // The clause the page in view belongs to: the last one starting on or before it
  const current = useMemo(() => {
    let found: OutlineEntry | null = null;
    for (const entry of data ?? []) if (tab && entry.page <= tab.page) found = entry;
    return found;
  }, [data, tab]);

  if (!tab || !doc) return <Empty>Open a document to see its clauses here.</Empty>;
  return (
    <div className="panel">
      <div className="panel-head">
        <strong>{doc.title}</strong>
        <input type="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter clauses by number or title" />
      </div>
      <div className="panel-body">
        <Status loading={loading} error={error} />
        {data && !data.length && <Empty>No clause headings were detected in this document.</Empty>}
        {entries.slice(0, SHOWN).map((entry) => (
          <button key={entry.block_id} type="button" className={`outline-row ${entry === current ? "on" : ""}`}
                  style={{ paddingLeft: 8 + (wanted ? 0 : (entry.level - 1) * 14) }}
                  onClick={() => app.openDoc({ docId: doc.id, page: entry.page, target: entry.bbox, blockId: entry.block_id, highlight: tab.highlight })}>
            <span className="grow"><strong>{entry.num}</strong> {entry.title}</span>
            <small className="muted">{entry.page}</small>
          </button>
        ))}
        {entries.length > SHOWN && <div className="muted">Showing the first {SHOWN} of {entries.length}; filter to narrow them.</div>}
      </div>
    </div>
  );
}
