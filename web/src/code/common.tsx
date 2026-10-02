import { useApp } from "../store";
import { CallNode, CodeSymbol, Usage } from "../types";
import { Badge, shortPath } from "../ui";

const LISTED = 200;   // Rows drawn per list

/** A symbol to click: opens its declaration and explores it in the inspector. */
export function SymbolLink({ symbol, prefix = "", note }: { symbol: CodeSymbol; prefix?: string; note?: string }) {
  const app = useApp();
  return (
    <button type="button" className="code-row" title={`${symbol.kind} · ${symbol.path}:${symbol.line}${note ? " · " + note : ""}`}
            onClick={() => { app.openCode({ fileId: symbol.file_id, path: symbol.path, line: symbol.line }); app.setSymbolId(symbol.id); app.setAt(null); }}>
      <span className="grow">{prefix}{symbol.qualified}</span>
      <small className="muted">{symbol.kind}</small>
    </button>
  );
}

/** Places in the code, each opening its line. */
export function UsageRows({ usages, showTarget = false }: { usages: Usage[]; showTarget?: boolean }) {
  const app = useApp();
  return (
    <>
      {usages.slice(0, LISTED).map((usage) => (
        <button key={usage.ref_id} type="button" className="code-row usage" title={`${usage.path} · in ${usage.from_name || "the file"}`}
                onClick={() => app.openCode({ fileId: usage.file_id, path: usage.path, line: usage.line })}>
          <span className="where">{shortPath(usage.path, 2)}:{usage.line}</span>
          <code>{usage.text.slice(0, 200)}</code>
          {showTarget && usage.target && <small className="muted">→ {usage.target}</small>}
        </button>
      ))}
      {usages.length > LISTED && <div className="muted">Showing the first {LISTED} of {usages.length}.</div>}
    </>
  );
}

export function CallTree({ nodes, level = 0 }: { nodes: CallNode[]; level?: number }) {
  return (
    <>
      {nodes.map((node) => (
        <div key={`${level}:${node.symbol.id}`} style={{ paddingLeft: level ? 14 : 0 }}>
          <SymbolLink symbol={node.symbol} prefix={level ? "└ " : ""}
                      note={`call at line ${node.line}${node.truncated ? " · more below, not followed" : ""}`} />
          <CallTree nodes={node.children} level={level + 1} />
        </div>
      ))}
    </>
  );
}

export function SymbolHead({ symbol }: { symbol: CodeSymbol }) {
  return (
    <>
      <header><Badge kind="object">{symbol.kind}</Badge><span className="card-title">{symbol.qualified}</span></header>
      <div className="card-path">{symbol.path}:{symbol.line}</div>
      <code className="signature">{symbol.signature}</code>
    </>
  );
}
