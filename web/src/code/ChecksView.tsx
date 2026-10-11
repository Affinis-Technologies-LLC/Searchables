// Convention checks (ADR-021): what breaks the codebase's own patterns, with the places that establish them.
import { useState } from "react";
import { api } from "../api";
import { useLoad } from "../hooks";
import { useApp } from "../store";
import { Codebase, Finding } from "../types";
import { Badge, Empty, shortPath, Status } from "../ui";

const KIND: Record<string, string> = { companion: "Missing companion", naming: "Naming", error: "One-off error", layering: "Layering" };

export function ChecksView({ codebase }: { codebase: Codebase }) {
  const app = useApp();
  const { data, loading, error } = useLoad<Finding[]>(() => api.get(`/codebases/${codebase.id}/checks`), [codebase.id, codebase.indexed_at, app.filesVersion]);
  const [open, setOpen] = useState<number | null>(null);
  return (
    <>
      <div className="panel-head"><div className="muted">Methods and types that break what this codebase usually does. The rules come from the code itself
        (Patterns); each finding shows the places that follow the rule. Findings are questions, not errors.</div></div>
      <div className="panel-body">
        <Status loading={loading && !data} error={error} />
        {data && !data.length && <Empty>Nothing breaks a pattern the codebase establishes.</Empty>}
        {data?.map((f, i) => (
          <article key={i} className="card" onClick={() => setOpen(open === i ? null : i)}>
            <header><Badge kind="object">{KIND[f.kind] ?? f.kind}</Badge><span className="card-title">{f.symbol.qualified.split(".").pop()}</span>
              <span className="muted">{Math.round(f.confidence * 100)}%</span></header>
            <div className="card-path"><button type="button" className="link" onClick={(e) => { e.stopPropagation(); app.openCode({ fileId: f.file_id, path: f.path, line: f.line }); }}>{shortPath(f.path, 2)}:{f.line}</button></div>
            <div>{f.message}</div>
            {open === i && (
              <div className="examples">
                <div className="muted">Follows the rule:</div>
                {f.examples.map((w, j) => (
                  <button key={j} type="button" className="code-row usage" onClick={(e) => { e.stopPropagation(); app.openCode({ fileId: w.file_id, path: w.path, line: w.line }); }}>
                    <span className="where">{shortPath(w.path, 2)}:{w.line}</span><code>{w.enclosing.split("#").pop() || w.enclosing}</code>
                  </button>
                ))}
              </div>
            )}
          </article>
        ))}
      </div>
    </>
  );
}
