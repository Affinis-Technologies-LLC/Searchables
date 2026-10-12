// Git history, read-only (ADR-026): a file's or a symbol's commits, one commit with its files and
// diff, and the blame column beside the editor. Nothing here writes.
import { useEffect, useState } from "react";
import * as monaco from "monaco-editor/esm/vs/editor/edcore.main";
import { api } from "../api";
import { useLoad } from "../hooks";
import { BlameLine, CodeSymbol, GitCommit, GitShown } from "../types";
import { Empty, shortPath, Status } from "../ui";
import type { CodeTab } from "../store";
import { useFile } from "./files";

export const COMMIT_EVENT = "searchables:commit";   // { codebaseId, commit, path }: open this commit in the inspector's History

export function DiffBlock({ text }: { text: string }) {
  if (!text.trim()) return <div className="muted">No changes to this file in that commit.</div>;
  return (
    <pre className="snippet diff">
      {text.split("\n").map((l, i) => (
        <div key={i} className={l.startsWith("+") && !l.startsWith("+++") ? "add" : l.startsWith("-") && !l.startsWith("---") ? "del" : ""}>{l}</div>
      ))}
    </pre>
  );
}

/** One commit: message, author, date, the files it changed, and its diff for one path. */
export function CommitPanel({ codebaseId, commit, path, onPath }: { codebaseId: number; commit: string; path?: string; onPath?: (path: string) => void }) {
  const shown = useLoad<GitShown>(() => api.get(`/codebases/${codebaseId}/git/show?commit=${encodeURIComponent(commit)}${path ? `&path=${encodeURIComponent(path)}` : ""}`), [codebaseId, commit, path]);
  return (
    <div className="commit">
      <Status loading={shown.loading && !shown.data} error={shown.error} />
      {shown.data && (
        <>
          <div><code>{shown.data.commit}</code> · {shown.data.date} · {shown.data.author}</div>
          <pre className="snippet message">{shown.data.message}</pre>
          <div className="group-title">Files changed · {shown.data.files.length}</div>
          {shown.data.files.map((f) => (
            <button key={f.path} type="button" className={"code-row" + (f.path === path ? " current" : "")} title={f.path}
                    onClick={() => onPath?.(f.path)} disabled={!onPath}>
              <span className="grow">{shortPath(f.path, 3)}</span><small className="muted">+{f.added} −{f.removed}</small>
            </button>
          ))}
          {path && <><div className="group-title">Diff · {shortPath(path, 2)}</div><DiffBlock text={shown.data.diff} /></>}
        </>
      )}
    </div>
  );
}

/** The commits that changed a file (renames followed) or a symbol's lines; one opens below the list. */
export function HistoryList({ codebaseId, path, start, end, chosen, onChoose }:
                            { codebaseId: number; path: string; start?: number; end?: number; chosen: string | null; onChoose: (commit: string | null) => void }) {
  const range = start && end ? `&start=${start}&end=${end}` : "";
  const history = useLoad<GitCommit[]>(() => api.get(`/codebases/${codebaseId}/git/history?path=${encodeURIComponent(path)}${range}`), [codebaseId, path, range]);
  return (
    <>
      <Status loading={history.loading && !history.data} error={history.error} />
      {history.data && !history.data.length && <Empty>No commits: not in a repository, or not committed yet.</Empty>}
      {history.data?.map((c) => (
        <button key={c.commit} type="button" className={"code-row" + (c.commit === chosen ? " current" : "")} title={c.message}
                onClick={() => onChoose(c.commit === chosen ? null : c.commit)}>
          <span className="where">{c.date}</span><span className="grow">{c.message}</span><small className="muted">{c.author} · <code>{c.commit}</code></small>
        </button>
      ))}
      {chosen && <CommitPanel codebaseId={codebaseId} commit={chosen} path={path} />}
    </>
  );
}

/** The inspector's History view: the symbol's commits when one is chosen, else the file's. A blame click lands here. */
export function HistoryView({ tab, symbol }: { tab: CodeTab; symbol: CodeSymbol | null }) {
  const { data } = useFile(tab.fileId);
  const [scope, setScope] = useState<"symbol" | "file">(symbol ? "symbol" : "file");
  const [chosen, setChosen] = useState<string | null>(null);
  useEffect(() => { setScope(symbol ? "symbol" : "file"); setChosen(null); }, [symbol?.id, tab.fileId]);
  useEffect(() => {
    const open = (e: Event) => {
      const detail = (e as CustomEvent<{ commit: string; path: string }>).detail;
      if (detail.path === tab.path) { setScope("file"); setChosen(detail.commit); }
    };
    window.addEventListener(COMMIT_EVENT, open);
    return () => window.removeEventListener(COMMIT_EVENT, open);
  }, [tab.path]);
  if (!data) return null;
  const ofSymbol = scope === "symbol" && symbol && symbol.file_id === tab.fileId;
  return (
    <>
      {symbol && symbol.file_id === tab.fileId && (
        <div className="row">
          <button type="button" className={ofSymbol ? "current" : ""} onClick={() => { setScope("symbol"); setChosen(null); }}>{symbol.name}</button>
          <button type="button" className={!ofSymbol ? "current" : ""} onClick={() => { setScope("file"); setChosen(null); }}>Whole file</button>
        </div>
      )}
      <div className="group-title">{ofSymbol ? `Commits that changed ${symbol!.name} (lines ${symbol!.line}–${symbol!.end_line})` : `Commits that changed ${shortPath(tab.path, 1)}`}</div>
      <HistoryList codebaseId={data.file.codebase_id} path={tab.path} start={ofSymbol ? symbol!.line : undefined} end={ofSymbol ? symbol!.end_line : undefined}
                   chosen={chosen} onChoose={setChosen} />
      <div className="muted">Read from git; renames are followed for a file. Nothing is written.</div>
    </>
  );
}

/** Who last changed each line, beside the editor; runs of the same commit show it once. */
export function BlameColumn({ editor, lines, dirty, onCommit }:
                            { editor: monaco.editor.IStandaloneCodeEditor; lines: BlameLine[]; dirty: boolean; onCommit: (commit: string) => void }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const scrolled = editor.onDidScrollChange(() => tick((n) => n + 1));
    const laidOut = editor.onDidLayoutChange(() => tick((n) => n + 1));
    return () => { scrolled.dispose(); laidOut.dispose(); };
  }, [editor]);
  const lineHeight = editor.getOption(monaco.editor.EditorOption.lineHeight);
  const top = editor.getScrollTop();
  const byLine = new Map(lines.map((l) => [l.line, l]));
  const visible = editor.getVisibleRanges();
  const rows: JSX.Element[] = [];
  for (const range of visible) {
    for (let n = range.startLineNumber; n <= range.endLineNumber; n++) {
      const l = byLine.get(n);
      const previous = byLine.get(n - 1);
      const same = !!l && !!previous && previous.commit === l.commit && previous.uncommitted === l.uncommitted;
      rows.push(
        <div key={n} className={"blame-line" + (l?.uncommitted ? " uncommitted" : "") + (same ? " same" : "")}
             style={{ top: editor.getTopForLineNumber(n) - top, height: lineHeight }}
             title={l ? (l.uncommitted ? "Not committed yet" : `${l.commit} · ${l.author} · ${l.date}\n${l.summary}`) : ""}
             onClick={() => l && !l.uncommitted && onCommit(l.commit)}>
          {l && !same && (l.uncommitted ? "uncommitted" : `${l.author.split(/\s+/).map((w) => w[0]).join("").slice(0, 3)} ${l.date}`)}
        </div>,
      );
    }
  }
  return (
    <div className="blame-column" title={dirty ? "Blame is of the file on disk; this tab has unsaved changes." : undefined}>
      {dirty && <div className="blame-note">on disk</div>}
      {rows}
    </div>
  );
}
