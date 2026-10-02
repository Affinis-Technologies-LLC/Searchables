import { useEffect, useState } from "react";
import { api, query } from "../api";
import { useLoad } from "../hooks";
import { useApp } from "../store";
import { ClauseDiff, Comparison, DocumentInfo } from "../types";
import { Badge, Chips, Empty, Status } from "../ui";

const STATUSES = ["Changed", "Added", "Removed", "Renumbered", "Unchanged"];

/** Two documents whose titles differ only by year or edition, older first; else the first two. */
function guessEditions(documents: DocumentInfo[]): [number, number] {
  const stems = new Map<string, DocumentInfo[]>();
  for (const doc of documents) {
    const stem = doc.title.toLowerCase().replace(/[\W_]*(?:19|20)\d\d\b.*$/, "");
    stems.set(stem, [...(stems.get(stem) ?? []), doc]);
  }
  for (const group of stems.values()) {
    if (group.length >= 2) {
      const sorted = [...group].sort((a, b) => a.title.localeCompare(b.title));
      return [sorted[sorted.length - 2].id, sorted[sorted.length - 1].id];
    }
  }
  return [documents[0].id, documents[1].id];
}

/** Clause-by-clause differences between two editions. */
export function ComparePanel() {
  const app = useApp();
  const { documents } = app.overview;
  const [older, setOlder] = useState<number | null>(null);
  const [newer, setNewer] = useState<number | null>(null);
  const [statuses, setStatuses] = useState(STATUSES.slice(0, 4));
  const [provisionsOnly, setProvisionsOnly] = useState(false);
  const [chosen, setChosen] = useState(false);
  const ids = documents.map((d) => d.id).join(",");
  useEffect(() => {
    // Until two are chosen here (and while both are still in the library), the likeliest pair of editions is offered
    const valid = documents.some((d) => d.id === older) && documents.some((d) => d.id === newer);
    if (documents.length >= 2 && !(chosen && valid)) {
      const [a, b] = guessEditions(documents);
      setOlder(a);
      setNewer(b);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids, chosen]);

  const ready = app.activity === "compare" && older !== null && newer !== null && older !== newer;
  const params = query({ old: older, new: newer });
  const { data, loading, error } = useLoad<Comparison>(() => (ready ? api.get(`/compare${params}`) : null), [ready, params]);

  if (documents.length < 2) return <Empty>Add two editions of a document to the library to compare them clause by clause.</Empty>;
  const visible = (d: ClauseDiff) => {
    const wanted = statuses.length ? statuses : STATUSES;
    const shown = wanted.includes(d.status[0].toUpperCase() + d.status.slice(1)) || (d.renumbered && wanted.includes("Renumbered"));
    return shown && (!provisionsOnly || d.provision_change !== "");
  };
  const shown = data?.diffs.filter(visible) ?? [];
  const pick = (value: number | null, set: (id: number) => void, label: string) => (
    <label className="grow">{label}
      <select value={value ?? ""} onChange={(e) => { set(Number(e.target.value)); setChosen(true); }}>
        {documents.map((d) => <option key={d.id} value={d.id}>{d.title}</option>)}
      </select>
    </label>
  );
  return (
    <div className="panel">
      <div className="panel-head">
        <div className="row">{pick(older, setOlder, "Older edition")}{pick(newer, setNewer, "Newer edition")}</div>
        {older === newer && <div className="notice">Choose two different documents.</div>}
        {data && (
          <>
            <div className="metrics">
              <span><strong>{data.counts.changed}</strong> changed</span>
              <span><strong>{data.counts.added}</strong> added</span>
              <span><strong>{data.counts.removed}</strong> removed</span>
              <span><strong>{data.renumbered}</strong> renumbered</span>
              <span title="Clauses whose count of shall / should / may changed"><strong>{data.provision_changes}</strong> requirement changes</span>
            </div>
            <Chips options={STATUSES} value={statuses} onChange={setStatuses} />
            <div className="row wrap">
              <label className="check"><input type="checkbox" checked={provisionsOnly} onChange={(e) => setProvisionsOnly(e.target.checked)} /> Only shall/should/may changes</label>
              <span className="grow" />
              <a className="link" href={`/api/compare${params}&format=md`}>Markdown</a>
              <a className="link" href={`/api/compare${params}&format=csv`}>CSV</a>
            </div>
          </>
        )}
      </div>
      <div className="panel-body">
        <Status loading={loading} error={error} />
        {data && <div className="summary"><span>{shown.length} of {data.diffs.length} clauses, in the newer edition's order</span></div>}
        {shown.map((diff, i) => {
          const ref = (diff.new ?? diff.old)!;
          return (
            <article key={i} className="card static">
              <header>
                <Badge kind={"diff-" + diff.status}>{diff.status}</Badge>
                {diff.renumbered && diff.old && <Badge>was {diff.old.num || diff.old.title}</Badge>}
                {diff.provision_change && <Badge kind="requirement">{diff.provision_change}</Badge>}
                <span className="card-title">{`${ref.num} ${ref.title}`.trim()}</span>
                {diff.status === "changed" && <span className="muted">{Math.round(diff.similarity * 100)}% similar</span>}
              </header>
              <div className="card-body diff">
                {diff.html ? <span dangerouslySetInnerHTML={{ __html: diff.html }} />
                  : diff.status === "changed" ? <em>Title changed only</em>
                  : diff.status === "unchanged" ? ref.text.slice(0, 300) + (ref.text.length > 300 ? "…" : "")
                  : ref.text || <em>Heading only</em>}
              </div>
              <footer>
                {diff.old && <button type="button" onClick={() => app.openDoc({ docId: older!, page: diff.old!.page, target: diff.old!.bbox })}>Older p. {diff.old.page}</button>}
                {diff.new && <button type="button" onClick={() => app.openDoc({ docId: newer!, page: diff.new!.page, target: diff.new!.bbox })}>Newer p. {diff.new.page}</button>}
              </footer>
            </article>
          );
        })}
      </div>
    </div>
  );
}
