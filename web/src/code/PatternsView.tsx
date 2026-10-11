// The Patterns view (ADR-013): what's usual in the codebase, each pattern opening the places it was counted from.
import { useState } from "react";
import { api } from "../api";
import { useLoad } from "../hooks";
import { useApp } from "../store";
import { ChainNode, Codebase, Patterns, Where } from "../types";
import { Empty, shortPath, Status } from "../ui";

const SECTIONS = ["Idioms", "How things are made", "Go together", "Entry points", "Hotspots", "Conventions", "Angular", "React"] as const;

export function PatternsView({ codebase }: { codebase: Codebase }) {
  const app = useApp();
  const { data, loading, error } = useLoad<Patterns>(() => api.get(`/codebases/${codebase.id}/patterns`), [codebase.id, codebase.indexed_at, app.filesVersion]);
  const [section, setSection] = useState<(typeof SECTIONS)[number]>("Idioms");
  const [open, setOpen] = useState<string | null>(null);
  const available = SECTIONS.filter((s) => !data || (s !== "Angular" || data.angular.length) && (s !== "React" || data.react.length));
  const places = (key: string, examples: Where[]) => open === key && (
    <div className="examples">
      {examples.map((w, i) => (
        <button key={i} type="button" className="code-row usage" title={w.path} onClick={() => app.openCode({ fileId: w.file_id, path: w.path, line: w.line })}>
          <span className="where">{shortPath(w.path, 2)}:{w.line}</span><code>{w.enclosing.split("#").pop() || w.enclosing}</code>
        </button>
      ))}
    </div>
  );
  const row = (key: string, title: string, detail: string, examples: Where[]) => (
    <div key={key} className="pattern">
      <button type="button" className="pattern-row" onClick={() => setOpen(open === key ? null : key)} aria-expanded={open === key}>
        <span className="grow">{title}</span><span className="muted">{detail}</span>
      </button>
      {places(key, examples)}
    </div>
  );
  return (
    <>
      <div className="panel-head">
        <select value={section} onChange={(e) => setSection(e.target.value as (typeof SECTIONS)[number])} aria-label="Pattern">
          {available.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <div className="muted">Counted over linked references only; open a row for the places it was counted from.</div>
      </div>
      <div className="panel-body">
        <Status loading={loading && !data} error={error} />
        {data && section === "Idioms" && (data.idioms.length ? data.idioms.map((idiom) => (
          <div key={idiom.type_id} className="group">
            <div className="group-title">{idiom.type_name} <span className="muted">· {idiom.call_sites} call sites</span></div>
            {idiom.members.map((m) => row(`m${idiom.type_id}.${m.name}`, `${m.name}`, `${m.calls} call${m.calls === 1 ? "" : "s"}`, m.examples))}
            {idiom.pairs.map((p) => row(`p${idiom.type_id}.${p.first}.${p.second}`, `${p.first} then ${p.second}`, `${p.methods} method${p.methods === 1 ? "" : "s"}`, p.examples))}
          </div>
        )) : <Empty>No type is called from three or more places yet.</Empty>)}
        {data && section === "How things are made" && data.made.map((m) => row(`made${m.type_id}`, m.type_name,
          [m.injected && `injected in ${m.injected}`, m.constructed && `constructed in ${m.constructed}`, m.factory && `from a factory in ${m.factory}`].filter(Boolean).join(" · "), m.examples))}
        {data && section === "Go together" && (data.pairs.length ? data.pairs.map((p) => row(`pair${p.first}.${p.second}`, `${p.first} goes with ${p.second}`,
          `${p.support} methods · ${Math.round(p.confidence * 100)}%`, p.examples)) : <Empty>No pair of calls appears together in three or more methods.</Empty>)}
        {data && section === "Entry points" && (
          <>
            {data.layers.length > 1 && <div className="group"><div className="group-title">Layers</div><div className="muted">{data.layers.join(" → ")}</div></div>}
            {data.entry_points.length ? data.entry_points.map((e) => (
              <div key={e.route + e.line} className="group">
                <button type="button" className="code-row usage" onClick={() => app.openCode({ fileId: e.file_id, path: e.path, line: e.line })}>
                  <span className="where">{e.route}</span><code>{e.handler.split("#").pop()}</code>
                </button>
                <Chain nodes={e.chain} level={1} />
              </div>
            )) : <Empty>No HTTP routes are served by this codebase.</Empty>}
          </>
        )}
        {data && section === "Hotspots" && (
          <>
            <div className="group-title">Most referenced symbols</div>
            {data.hot_symbols.map((h) => row(`hot${h.symbol_id}`, h.qualified.split(".").pop() ?? h.name, `${h.references} references`, h.examples))}
            <div className="group-title">Most referenced files</div>
            {data.hot_files.map((f) => (
              <button key={f.file_id} type="button" className="code-row usage" onClick={() => app.openCode({ fileId: f.file_id, path: f.path, line: 1 })}>
                <span className="where">{f.references}</span><code>{shortPath(f.path, 3)}</code>
              </button>
            ))}
          </>
        )}
        {data && section === "Conventions" && (
          <>
            <div className="group-title">Naming</div>
            {data.naming.length ? data.naming.map((n) => row(`name${n.package}`, `Types in ${n.package || "the top folder"} end in ${n.suffix}`, `${n.count} of ${n.total}`, n.examples))
                                : <div className="muted">No package names most of its types the same way.</div>}
            <div className="group-title">Where tests live</div>
            <div className="muted">{data.test_folders.length ? data.test_folders.join(", ") : "No folder holds mostly tests."}</div>
            <div className="group-title">How errors are raised</div>
            {data.errors.length ? data.errors.map((e) => row(`err${e.type_name}`, `throw new ${e.type_name}`, `${e.count}`, e.examples)) : <div className="muted">No throw statements found.</div>}
          </>
        )}
        {data && section === "Angular" && data.angular.map((c) => (
          <article key={c.symbol_id} className="card" onClick={() => app.openCode({ fileId: c.file_id, path: c.path, line: c.line })}>
            <header><span className="card-title">{c.name}</span><code className="muted">&lt;{c.selector}&gt;</code></header>
            <div className="card-path">{c.template ? shortPath(c.template, 2) : "inline template"}</div>
            <div className="muted">
              {c.inputs.length > 0 && <>Inputs: {c.inputs.join(", ")} · </>}
              {c.outputs.length > 0 && <>Outputs: {c.outputs.join(", ")} · </>}
              {c.injected.length > 0 && <>Injects: {c.injected.join(", ")} · </>}
              {c.renders.length > 0 && <>Renders: {c.renders.join(", ")}</>}
            </div>
          </article>
        ))}
        {data && section === "React" && data.react.map((c) => (
          <article key={c.symbol_id} className="card" onClick={() => app.openCode({ fileId: c.file_id, path: c.path, line: c.line })}>
            <header><span className="card-title">{c.name}</span></header>
            <div className="card-path">{shortPath(c.path, 2)}</div>
            <div className="muted">
              {c.renders.length > 0 && <>Renders: {c.renders.join(", ")} · </>}
              {c.hooks.length > 0 ? <>Hooks: {c.hooks.join(", ")}</> : "No hooks"}
            </div>
          </article>
        ))}
      </div>
    </>
  );
}

function Chain({ nodes, level }: { nodes: ChainNode[]; level: number }) {
  const app = useApp();
  return (
    <>
      {nodes.map((n, i) => (
        <div key={i}>
          <button type="button" className="code-row usage" style={{ paddingLeft: 8 + level * 14 }} onClick={() => app.setSymbolId(n.symbol_id)}>
            <span className="where">→</span><code>{n.symbol.split("#").pop()}</code><span className="muted"> {n.symbol.split("#")[0].split(".").pop()}</span>
          </button>
          {n.children.length > 0 && <Chain nodes={n.children} level={level + 1} />}
        </div>
      ))}
    </>
  );
}
