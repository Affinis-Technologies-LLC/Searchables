// Dead and unreachable code (ADR-019): what the index never sees referenced, with its certainty.
import { useState } from "react";
import { api } from "../api";
import { useLoad } from "../hooks";
import { useApp } from "../store";
import { Codebase, CodeSymbol, UnusedItem, UnusedReport } from "../types";
import { Badge, Empty, shortPath, Status } from "../ui";

export function UnusedView({ codebase }: { codebase: Codebase }) {
  const app = useApp();
  const [byName, setByName] = useState(false);
  const { data, loading, error } = useLoad<UnusedReport>(() => api.get(`/codebases/${codebase.id}/unused`), [codebase.id, codebase.indexed_at, app.filesVersion]);
  const open = (s: CodeSymbol) => { app.openCode({ fileId: s.file_id, path: s.path, line: s.line }); app.setSymbolId(s.id); app.setAt(null); };
  const rows = (items: UnusedItem[]) => items.map((u) => (
    <button key={u.symbol.id} type="button" className="code-row usage" title={u.symbol.qualified} onClick={() => open(u.symbol)}>
      <span className="where">{shortPath(u.symbol.path, 2)}:{u.symbol.line}</span>
      <code>{u.symbol.qualified.split(".").pop()}</code>
      {u.certainty === "name" && <span className="muted"> · {u.by_name_references} by-name reference{u.by_name_references === 1 ? "" : "s"}</span>}
    </button>
  ));
  return (
    <>
      <div className="panel-head">
        <div className="muted">Declared but never referenced anywhere the index can see. Routes, tests, entry points, lifecycle methods and
          annotated methods are never listed.</div>
        <label className="check" title="Symbols whose only references agree by name: not dead, uncertain">
          <input type="checkbox" checked={byName} onChange={(e) => setByName(e.target.checked)} /> Show symbols with by-name references only
        </label>
      </div>
      <div className="panel-body">
        <Status loading={loading && !data} error={error} />
        {data && (
          <>
            <div className="group-title">Methods and functions nothing calls <span className="muted">· {data.methods.length}</span></div>
            {data.methods.length ? rows(data.methods) : <div className="muted">None.</div>}
            {byName && (
              <>
                <div className="group-title">Only by-name references <Badge kind="name">uncertain</Badge> <span className="muted">· {data.by_name_only.length}</span></div>
                {data.by_name_only.length ? rows(data.by_name_only) : <div className="muted">None.</div>}
              </>
            )}
            <div className="group-title">Routes nothing calls <span className="muted">· {data.routes.length}</span></div>
            {data.routes.length ? data.routes.map((r) => (
              <button key={r.route + r.line} type="button" className="code-row usage" onClick={() => app.openCode({ fileId: r.file_id, path: r.path, line: r.line })}>
                <span className="where">{r.route}</span><code>{r.handler?.qualified.split("#").pop() ?? shortPath(r.path, 2)}</code>
              </button>
            )) : <div className="muted">None.</div>}
            <div className="group-title">Exports nothing imports <span className="muted">· {data.exports.length}</span></div>
            {data.exports.length ? rows(data.exports) : <div className="muted">None.</div>}
            <div className="group-title">Types nothing refers to <span className="muted">· {data.types.length}</span></div>
            {data.types.length ? rows(data.types) : <div className="muted">None.</div>}
            {!data.methods.length && !data.routes.length && !data.exports.length && !data.types.length && <Empty>Everything is referenced somewhere.</Empty>}
          </>
        )}
      </div>
    </>
  );
}
