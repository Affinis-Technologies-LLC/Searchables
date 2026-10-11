import { useEffect, useState } from "react";
import { api, query } from "../api";
import { useLoad } from "../hooks";
import { CodeTab, useApp } from "../store";
import { Calls, CodeSymbol, FileIdentifier, Impact, SymbolDetail, Usage } from "../types";
import { CopyButton, Empty, Icon, Segments, Status } from "../ui";
import { CallTree, SymbolHead, SymbolLink, UsageRows } from "./common";
import { ExamplesPanel } from "./ExamplesPanel";
import { RenameDialog } from "./RenameDialog";
import { loadFile, useFile } from "./files";

const VIEWS = ["Examples", "Usages", "Calls", "Impact", "Hierarchy", "Members", "File"] as const;
const CERTAINTY: [Usage["certainty"], string, string][] = [
  ["resolved", "Linked", "Followed through imports, declared types or scope."],
  ["supertype", "Through a supertype", "Calls made through an interface or superclass method that this one implements or overrides."],
  ["name", "By name only", "The name and number of arguments agree, but what it's called on couldn't be told without compiling the code. Check these before relying on them."],
];

/** Beside the source: the symbol under the cursor — its usages, callers and callees, hierarchy — and the file's outline. */
export function CodeInspector({ tab }: { tab: CodeTab }) {
  const app = useApp();
  const view = (VIEWS as readonly string[]).includes(app.inspectorView) ? app.inspectorView as (typeof VIEWS)[number] : "Usages";
  const setView = app.setInspectorView;
  const file = useFile(tab.fileId);
  const [renaming, setRenaming] = useState(false);
  const detail = useLoad<SymbolDetail>(() => (app.symbolId !== null ? api.get(`/code/symbols/${app.symbolId}`) : null), [app.symbolId]);
  const symbol = detail.data?.symbol ?? null;
  const loose = app.at?.ref && !app.at.target ? app.at : null;   // Under the cursor: an outside API, or a call that isn't linked
  const views = VIEWS.filter((v) => v !== "Members" || !!detail.data?.members.length);
  useEffect(() => { if (view === "Members" && symbol && !detail.data?.members.length) setView("Usages"); }, [view, symbol, detail.data]);

  return (
    <div className="panel">
      <div className="panel-head">
        {loose ? (
          <div className="symbol-head">
            <header><span className="card-title">{loose.ref!.name}</span></header>
            <div className="card-path">{loose.ref!.target ? `Outside API: ${loose.ref!.target}` : "Couldn't be linked for certain"}</div>
          </div>
        ) : symbol ? (
          <div className="symbol-head">
            <SymbolHead symbol={symbol} />
            <div className="row">
              <button type="button" onClick={() => app.openCode({ fileId: symbol.file_id, path: symbol.path, line: symbol.line })}>Show declaration</button>
              <CopyButton title="Copy its source" text={async () => {
                const source = (await loadFile(symbol.file_id)).text.split("\n").slice(symbol.line - 1, symbol.end_line).join("\n");
                return app.cite ? `${source}\n// ${symbol.path}:${symbol.line}` : source;
              }} />
              <button type="button" onClick={() => app.pinSymbol(symbol.id)} title="Save its source to the active collection"><Icon name="pin" size={13} /> Pin</button>
              {["method", "function", "field", "variable", "class", "interface", "enum", "record", "type"].includes(symbol.kind) && (
                <button type="button" onClick={() => setRenaming(true)} title="Rename it everywhere, after a preview">Rename…</button>
              )}
            </div>
            {renaming && <RenameDialog symbol={symbol} onClose={() => setRenaming(false)} />}
          </div>
        ) : null}
        {!loose && <Segments options={views} value={view} onChange={setView} />}
      </div>
      <div className="panel-body">
        <Status loading={detail.loading && !detail.data} error={detail.error} />
        {loose && file.data && <Loose codebaseId={file.data.file.codebase_id} target={loose.ref!.target} candidates={loose.candidates} />}
        {!loose && view === "File" && <FileView tab={tab} />}
        {!loose && view === "Examples" && <ExamplesPanel />}
        {!loose && view !== "File" && view !== "Examples" && !symbol && !detail.loading && (
          <Empty>Put the cursor on a name in the source, or pick a symbol from the search or the file's outline, to see
            where it's used, what calls it and what it calls.</Empty>
        )}
        {!loose && symbol && view === "Usages" && <Usages symbol={symbol} />}
        {!loose && symbol && view === "Calls" && <CallsView symbol={symbol} />}
        {!loose && symbol && view === "Impact" && <ImpactView symbol={symbol} />}
        {!loose && symbol && detail.data && view === "Hierarchy" && <Hierarchy detail={detail.data} />}
        {!loose && symbol && detail.data && view === "Members" &&
          detail.data.members.map((m) => <SymbolLink key={m.id} symbol={m} note={m.signature} />)}
      </div>
    </div>
  );
}

function Loose({ codebaseId, target, candidates }: { codebaseId: number; target: string; candidates: CodeSymbol[] }) {
  const usages = useLoad<Usage[]>(() => (target ? api.get(`/codebases/${codebaseId}/external${query({ target })}`) : null), [codebaseId, target]);
  return (
    <>
      {!target && (
        candidates.length ? (
          <>
            <div className="group-title">Declarations with this name · {candidates.length}</div>
            <div className="muted">What it's called on couldn't be told without compiling the code, so any of these may be meant.</div>
            {candidates.map((c) => <SymbolLink key={c.id} symbol={c} />)}
          </>
        ) : <Empty>Nothing in this codebase declares it; it's probably part of the language or of a library that couldn't be identified.</Empty>
      )}
      <Status loading={usages.loading} error={usages.error} />
      {usages.data && (
        <>
          <div className="group-title">Used in this codebase · {usages.data.length}</div>
          <UsageRows usages={usages.data} />
        </>
      )}
    </>
  );
}

function Usages({ symbol }: { symbol: CodeSymbol }) {
  const { data, loading, error } = useLoad<Usage[]>(() => api.get(`/code/symbols/${symbol.id}/usages`), [symbol.id]);
  return (
    <>
      <Status loading={loading} error={error} />
      {data && !data.length && <Empty>No references to it were found in this codebase.</Empty>}
      {data && CERTAINTY.map(([certainty, title, help]) => {
        const group = data.filter((u) => u.certainty === certainty);
        if (!group.length) return null;
        return (
          <section key={certainty}>
            <div className="group-title" title={help}>{title} · {group.length}</div>
            {certainty === "name" && <div className="muted">{help}</div>}
            <UsageRows usages={group} />
          </section>
        );
      })}
    </>
  );
}

function CallsView({ symbol }: { symbol: CodeSymbol }) {
  const [direction, setDirection] = useState<"callers" | "callees">("callers");
  const { data, loading, error } = useLoad<Calls>(() => api.get(`/code/symbols/${symbol.id}/calls?direction=${direction}`), [symbol.id, direction]);
  return (
    <>
      <Segments options={["callers", "callees"] as const} value={direction} onChange={setDirection}
                labels={{ callers: "Who calls it", callees: "What it calls" }} />
      <Status loading={loading} error={error} />
      {data && (
        <>
          <div className="group-title">{direction === "callers" ? "Callers" : "Calls"}, {data.depth} levels deep (linked calls only)</div>
          {data.tree.length ? <CallTree nodes={data.tree} /> : <div className="muted">None that could be linked for certain.</div>}
          {data.outside.length > 0 && (
            <>
              <div className="group-title">Calls to outside APIs · {data.outside.length}</div>
              <UsageRows usages={data.outside} showTarget />
            </>
          )}
          {data.unlinked.length > 0 && (
            <>
              <div className="group-title">{direction === "callers" ? "Possible callers" : "Calls that couldn't be linked"} · {data.unlinked.length}</div>
              <UsageRows usages={data.unlinked} />
            </>
          )}
        </>
      )}
    </>
  );
}

function Hierarchy({ detail }: { detail: SymbolDetail }) {
  const h = detail.hierarchy;
  const sections: [string, CodeSymbol[]][] = [
    ["Extends / implements", h.supertypes], ["Extended / implemented by", h.subtypes],
    ["Overrides or implements", h.overrides], ["Overridden or implemented by", h.overridden_by],
  ];
  const empty = sections.every(([, items]) => !items.length) && !h.external_supertypes.length;
  return (
    <>
      {empty && <Empty>No supertypes, subtypes or overrides in this codebase.</Empty>}
      {sections.map(([title, items]) => items.length > 0 && (
        <section key={title}>
          <div className="group-title">{title} · {items.length}</div>
          {items.map((item) => <SymbolLink key={item.id} symbol={item} />)}
        </section>
      ))}
      {h.external_supertypes.length > 0 && (
        <section>
          <div className="group-title">Outside supertypes</div>
          {h.external_supertypes.map((name) => <div key={name}><code>{name}</code></div>)}
        </section>
      )}
    </>
  );
}

function FileView({ tab }: { tab: CodeTab }) {
  const app = useApp();
  const { data, loading, error } = useFile(tab.fileId);
  if (!data) return <Status loading={loading} error={error} />;
  const depth = new Map<number, number>();
  return (
    <>
      <FileIdentifiers fileId={tab.fileId} />
      <div className="group-title">Outline · {data.outline.length}</div>
      {!data.outline.length && <div className="muted">No declarations found in this file.</div>}
      {data.outline.map((symbol) => {
        const level = symbol.parent_id !== null ? (depth.get(symbol.parent_id) ?? -1) + 1 : 0;
        depth.set(symbol.id, level);
        return (
          <button key={symbol.id} type="button" className="code-row" style={{ paddingLeft: 6 + level * 14 }} title={symbol.signature}
                  onClick={() => { app.openCode({ fileId: symbol.file_id, path: symbol.path, line: symbol.line }); app.setSymbolId(symbol.id); app.setAt(null); }}>
            <span className="grow">{symbol.name}</span><small className="muted">{symbol.kind} · {symbol.line}</small>
          </button>
        );
      })}
      <div className="group-title">This file imports · {data.imports.length}</div>
      {data.imports.map((item, i) => item.target_file !== null ? (
        <button key={i} type="button" className="code-row" title={item.target_path ?? ""}
                onClick={() => app.openCode({ fileId: item.target_file!, path: item.target_path!, line: 1 })}>
          <span className="grow"><code>{item.spec}</code></span><small className="muted">{item.target_path?.split("/").pop()}</small>
        </button>
      ) : (
        <div key={i} className="code-row plain"><span className="grow"><code>{item.spec}</code></span>
          <small className="muted">{item.external ? `outside: ${item.external}` : "not found here"}</small></div>
      ))}
      <div className="group-title">Imported by · {data.imported_by.length}</div>
      {data.imported_by.map((item, i) => (
        <button key={i} type="button" className="code-row" title={item.path}
                onClick={() => app.openCode({ fileId: item.file_id, path: item.path, line: item.line })}>
          <span className="grow">{item.path.split("/").slice(-2).join("/")}</span><small className="muted">line {item.line}</small>
        </button>
      ))}
    </>
  );
}


/** What could break: everything that reaches the symbol through calls, by layer, with the routes and tests among them. */
function ImpactView({ symbol }: { symbol: CodeSymbol }) {
  const app = useApp();
  const [byName, setByName] = useState(false);
  const { data, loading, error } = useLoad<Impact>(() => api.get(`/code/symbols/${symbol.id}/impact` + query({ by_name: byName })), [symbol.id, byName, app.filesVersion]);
  const label = (c: Usage["certainty"]) => CERTAINTY.find(([k]) => k === c)?.[1] ?? c;
  return (
    <>
      <div className="row">
        <label className="check" title="Also follow links that agree by name only; the nodes they add are marked">
          <input type="checkbox" checked={byName} onChange={(e) => setByName(e.target.checked)} /> Include by-name links
        </label>
      </div>
      <Status loading={loading && !data} error={error} />
      {data && !data.nodes.length && <Empty>Nothing in the codebase reaches this symbol through calls.</Empty>}
      {data && data.nodes.length > 0 && (
        <div className="summary">
          <span>{data.nodes.length} symbol{data.nodes.length === 1 ? "" : "s"} reach it{data.truncated ? " (cut: depth or size limit)" : ""}</span>
        </div>
      )}
      {data && data.routes.length > 0 && (
        <div className="group">
          <div className="group-title">Routes affected</div>
          {data.routes.map((r) => (
            <button key={r.route + r.handler_id} type="button" className="code-row usage" onClick={() => app.setSymbolId(r.handler_id)}>
              <span className="where">{r.route}</span><code>{r.handler.split("#").pop()}</code><span className="muted"> · {r.depth} call{r.depth === 1 ? "" : "s"} away</span>
            </button>
          ))}
        </div>
      )}
      {data && data.tests.length > 0 && (
        <div className="group">
          <div className="group-title">Tests that reach it</div>
          {data.tests.map((t) => (
            <button key={t.file_id} type="button" className="code-row usage" title={t.symbols.join(", ")} onClick={() => app.openCode({ fileId: t.file_id, path: t.path, line: 1 })}>
              <span className="where">{t.symbols.length}</span><code>{t.path.split("/").pop()}</code>
            </button>
          ))}
        </div>
      )}
      {data?.layers.map((layer) => (
        <div key={layer.layer} className="group">
          <div className="group-title">{layer.layer || "top folder"} <span className="muted">· {layer.nodes.length}</span></div>
          {layer.nodes.map((n) => (
            <button key={n.symbol_id} type="button" className="code-row usage" title={`${n.qualified} · reaches ${n.via === symbol.id ? symbol.qualified : "the symbol"} at line ${n.via_line} · ${label(n.certainty)}`}
                    style={{ paddingLeft: 8 + (n.depth - 1) * 10 }} onClick={() => app.openCode({ fileId: n.file_id, path: n.path, line: n.via_line })}>
              <span className="where">{n.depth}</span><code>{n.qualified.split(".").pop()}</code>
              {n.certainty !== "resolved" && <span className="muted"> · {label(n.certainty)}</span>}
            </button>
          ))}
        </div>
      ))}
    </>
  );
}


/** The Catalogue's identifiers mentioned in the file (ADR-014): mentions, labelled, opening the Catalogue entry. */
function FileIdentifiers({ fileId }: { fileId: number }) {
  const app = useApp();
  const { data } = useLoad<FileIdentifier[]>(() => (app.overview.documents.length ? api.get(`/code/files/${fileId}/identifiers`) : null), [fileId, app.filesVersion]);
  if (!data?.length) return null;
  return (
    <>
      <div className="group-title" title="Identifiers from the documents whose text appears here, or that a symbol is named after">Identifiers from the documents · {data.length}</div>
      {data.map((i, n) => (
        <button key={n} type="button" className="code-row usage" title={i.text} onClick={() => { app.setActivity("catalogue"); window.dispatchEvent(new CustomEvent("searchables:identifier", { detail: i.identifier })); }}>
          <span className="where">{i.line}</span><code>{i.identifier}</code>{i.certainty === "name" && <span className="muted"> · by name</span>}
        </button>
      ))}
    </>
  );
}
