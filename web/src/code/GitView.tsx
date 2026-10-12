// Git status, diff and commit (ADR-015): what changed on disk, and keeping it. Never a push.
import { useState, useSyncExternalStore } from "react";
import { api } from "../api";
import { useLoad } from "../hooks";
import { useApp } from "../store";
import { Codebase, GitCommit, GitInfo } from "../types";
import { Empty, shortPath, Status } from "../ui";
import { drafts } from "./drafts";
import { CommitPanel, DiffBlock } from "./history";

const STATUS: Record<string, string> = { "??": "new", " M": "modified", "M ": "modified (staged)", "MM": "modified", "A ": "added", " D": "deleted", "D ": "deleted", "R ": "renamed", "AM": "added" };

export function GitView({ codebase }: { codebase: Codebase }) {
  const app = useApp();
  const [version, setVersion] = useState(0);
  const { data, loading, error } = useLoad<GitInfo>(() => api.get(`/codebases/${codebase.id}/git`), [codebase.id, codebase.indexed_at, app.filesVersion, version]);
  const log = useLoad<GitCommit[]>(() => (data?.repository ? api.get(`/codebases/${codebase.id}/git/log`) : null), [codebase.id, data?.repository, version]);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [showing, setShowing] = useState<string | null>(null);
  const diff = useLoad<{ diff: string }>(() => (showing ? api.get(`/codebases/${codebase.id}/git/diff?path=${encodeURIComponent(showing)}`) : null), [codebase.id, showing, version, app.filesVersion]);
  const [message, setMessage] = useState("");
  const [opened, setOpened] = useState<string | null>(null);
  const [openedPath, setOpenedPath] = useState<string | null>(null);
  const dirty = useSyncExternalStore((l) => drafts.subscribe(l), () => drafts.dirtyIds().join(","));
  const unsavedPaths = new Set(dirty.split(",").filter(Boolean).map((id) => drafts.get(Number(id))?.path));
  const toggle = (path: string) => setChosen((c) => { const next = new Set(c); if (!next.delete(path)) next.add(path); return next; });
  const commit = async () => {
    const result = await app.run(api.post<{ commit: string }>(`/codebases/${codebase.id}/git/commit`, { paths: [...chosen], message }));
    if (result) { app.notify(`Committed ${result.commit}.`); setChosen(new Set()); setMessage(""); setVersion((n) => n + 1); }
  };
  return (
    <>
      <div className="panel-head">
        <Status loading={loading && !data} error={error} />
        {data && !data.repository && <div className="muted">Not available: {data.reason}. The folder must be inside a git repository and git must be installed.</div>}
        {data?.repository && (
          <>
            <div className="muted">Branch <b>{data.branch}</b> · {data.entries.length} changed file{data.entries.length === 1 ? "" : "s"}. Status, diff and commit only; the app never pushes.</div>
            <textarea value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Commit message" aria-label="Commit message" rows={2} />
            <div className="row">
              <button type="button" disabled={!chosen.size || !message.trim()} onClick={commit}>Commit {chosen.size ? `${chosen.size} file${chosen.size === 1 ? "" : "s"}` : ""}</button>
              <button type="button" onClick={() => setChosen(new Set(data.entries.map((e) => e.path)))}>All</button>
              <button type="button" onClick={() => setChosen(new Set())}>None</button>
            </div>
          </>
        )}
      </div>
      <div className="panel-body">
        {data?.repository && !data.entries.length && <Empty>Nothing has changed since the last commit.</Empty>}
        {data?.entries.map((e) => (
          <div key={e.path} className="row line">
            <input type="checkbox" checked={chosen.has(e.path)} onChange={() => toggle(e.path)} aria-label={`Commit ${e.path}`} />
            <button type="button" className="code-row usage grow" title={e.path} onClick={() => setShowing(showing === e.path ? null : e.path)}>
              <span className="where">{STATUS[e.status] ?? e.status.trim()}</span><code>{shortPath(e.path, 3)}</code>
              {unsavedPaths.has(e.path) && <span className="unsaved" title="Unsaved changes in the editor; what's on disk is what gets committed"> ●</span>}
            </button>
          </div>
        ))}
        {showing && (
          <div className="group">
            <div className="group-title">Diff · {shortPath(showing, 2)}</div>
            <Status loading={diff.loading && !diff.data} error={diff.error} />
            {diff.data && <DiffBlock text={diff.data.diff} />}
          </div>
        )}
        {log.data && log.data.length > 0 && (
          <div className="group">
            <div className="group-title">Recent commits</div>
            {log.data.map((c) => (
              <button key={c.commit} type="button" className={"code-row" + (c.commit === opened ? " current" : "")} title={c.message}
                      onClick={() => { setOpened(c.commit === opened ? null : c.commit); setOpenedPath(null); }}>
                <span className="where">{c.date}</span><span className="grow">{c.message}</span><small className="muted">{c.author} · <code>{c.commit}</code></small>
              </button>
            ))}
            {opened && <CommitPanel codebaseId={codebase.id} commit={opened} path={openedPath ?? undefined} onPath={setOpenedPath} />}
          </div>
        )}
      </div>
    </>
  );
}
