import { useEffect, useState } from "react";
import { api, query } from "../api";
import { useLoad } from "../hooks";
import { CodeTab, useApp } from "../store";
import { Calls, CodeSymbol, SymbolDetail, Usage } from "../types";
import { Empty, Icon, Segments, Status } from "../ui";
import { CallTree, SymbolHead, SymbolLink, UsageRows } from "./common";
import { useFile } from "./files";

const VIEWS = ["Usages", "Calls", "Hierarchy", "Members", "File"] as const;
const CERTAINTY: [Usage["certainty"], string, string][] = [
  ["resolved", "Linked", "Followed through imports, declared types or scope."],
  ["supertype", "Through a supertype", "Calls made through an interface or superclass method that this one implements or overrides."],
  ["name", "By name only", "The name and number of arguments agree, but what it's called on couldn't be told without compiling the code. Check these before relying on them."],
];

/** Beside the source: the symbol under the cursor — its usages, callers and callees, hierarchy — and the file's outline. */
export function CodeInspector({ tab }: { tab: CodeTab }) {
  const app = useApp();
  const [view, setView] = useState<(typeof VIEWS)[number]>("Usages");
  const file = useFile(tab.fileId);
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
              <button type="button" onClick={() => app.pinSymbol(symbol.id)} title="Save its source to the active collection"><Icon name="pin" size={13} /> Pin</button>
            </div>
          </div>
        ) : null}
        {!loose && <Segments options={views} value={view} onChange={setView} />}
      </div>
      <div className="panel-body">
        <Status loading={detail.loading && !detail.data} error={detail.error} />
        {loose && file.data && <Loose codebaseId={file.data.file.codebase_id} target={loose.ref!.target} candidates={loose.candidates} />}
        {!loose && view === "File" && <FileView tab={tab} />}
        {!loose && view !== "File" && !symbol && !detail.loading && (
          <Empty>Put the cursor on a name in the source, or pick a symbol from the search or the file's outline, to see
            where it's used, what calls it and what it calls.</Empty>
        )}
        {!loose && symbol && view === "Usages" && <Usages symbol={symbol} />}
        {!loose && symbol && view === "Calls" && <CallsView symbol={symbol} />}
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
