// Index snapshots, diffed (ADR-020): what a change did to the symbols, and whom it affects.
import { useState } from "react";
import { api } from "../api";
import { useLoad } from "../hooks";
import { useApp } from "../store";
import { Codebase, CodeSymbol, IndexDiff, Snapshot } from "../types";
import { Empty, shortPath, Status } from "../ui";
import { UsageRows } from "./common";

export function ChangesView({ codebase }: { codebase: Codebase }) {
  const app = useApp();
  const [label, setLabel] = useState("");
  const [against, setAgainst] = useState("");
  const [version, setVersion] = useState(0);
  const snapshots = useLoad<Snapshot[]>(() => api.get(`/codebases/${codebase.id}/snapshots`), [codebase.id, version]);
  const diff = useLoad<IndexDiff>(() => (against ? api.get(`/codebases/${codebase.id}/diff?against=${encodeURIComponent(against)}`) : null),
                                  [codebase.id, codebase.indexed_at, app.filesVersion, against]);
  const others = app.overview.codebases.filter((c) => c.id !== codebase.id && c.indexed_at);
  const take = async () => {
    if (await app.run(api.post(`/codebases/${codebase.id}/snapshots`, { label }))) { setLabel(""); setVersion((n) => n + 1); app.notify("Snapshot taken."); }
  };
  const remove = async (id: number) => {
    if (await app.run(api.del(`/code/snapshots/${id}`))) { if (against === `snapshot:${id}`) setAgainst(""); setVersion((n) => n + 1); }
  };
  const open = (s: CodeSymbol) => { if (s.id) { app.openCode({ fileId: s.file_id, path: s.path, line: s.line }); app.setSymbolId(s.id); app.setAt(null); } };
  const row = (s: CodeSymbol, extra = "") => (
    <button key={`${s.kind}:${s.qualified}:${s.params}`} type="button" className="code-row usage" title={s.qualified} onClick={() => open(s)} disabled={!s.id}>
      <span className="where">{shortPath(s.path, 2)}:{s.line}</span><code>{s.qualified.split(".").pop()}</code>{extra && <span className="muted"> · {extra}</span>}
    </button>
  );
  return (
    <>
      <div className="panel-head">
        <div className="row">
          <input type="text" className="grow" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Label for a snapshot of the index now" aria-label="Snapshot label" />
          <button type="button" onClick={take}>Take snapshot</button>
        </div>
        <select value={against} onChange={(e) => setAgainst(e.target.value)} aria-label="Compare against">
          <option value="">Compare the index now against…</option>
          {snapshots.data?.map((s) => <option key={s.id} value={`snapshot:${s.id}`}>snapshot “{s.label}” ({s.taken_at.replace("T", " ")}, {s.symbol_count} symbols)</option>)}
          {others.map((c) => <option key={c.id} value={`codebase:${c.id}`}>codebase {c.name}</option>)}
        </select>
        {snapshots.data && snapshots.data.length > 0 && (
          <div className="row wrap muted">
            {snapshots.data.map((s) => <span key={s.id}>{s.label} <button type="button" className="quiet" onClick={() => remove(s.id)} title="Delete this snapshot">×</button></span>)}
          </div>
        )}
      </div>
      <div className="panel-body">
        <Status loading={diff.loading && !diff.data} error={diff.error || snapshots.error} />
        {!against && <Empty>Take a snapshot before a change, make the change, rescan, and compare: symbols added, removed, changed or moved,
          and the callers affected. Two checkouts indexed as two codebases compare the same way.</Empty>}
        {diff.data && (
          <>
            <div className="summary"><span>{diff.data.added.length} added · {diff.data.removed.length} removed · {diff.data.changed.length} changed · {diff.data.moved.length} moved
              · calls by name {diff.data.by_name_before} → {diff.data.by_name_now}</span></div>
            {diff.data.changed.length > 0 && <div className="group-title">Changed signatures</div>}
            {diff.data.changed.map((c) => (
              <div key={c.now.id} className="group">
                {row(c.now, `was ${c.before_signature}`)}
                {c.callers.length > 0 && <div className="muted" style={{ paddingLeft: 10 }}>{c.callers.length} caller{c.callers.length === 1 ? "" : "s"} affected:</div>}
                <UsageRows usages={c.callers} />
              </div>
            ))}
            {diff.data.removed.length > 0 && <div className="group-title">Removed</div>}
            {diff.data.removed.map((s) => row(s, `${diff.data!.removed_callers[s.qualified] ?? 0} callers before · ${diff.data!.removed_by_name_now[s.qualified] ?? 0} by-name references now`))}
            {diff.data.added.length > 0 && <div className="group-title">Added</div>}
            {diff.data.added.map((s) => row(s))}
            {diff.data.moved.length > 0 && <div className="group-title">Moved</div>}
            {diff.data.moved.map((m) => row(m.now, `from ${shortPath(m.before_path, 2)}`))}
            {!diff.data.added.length && !diff.data.removed.length && !diff.data.changed.length && !diff.data.moved.length && <Empty>No symbol differs.</Empty>}
          </>
        )}
      </div>
    </>
  );
}
