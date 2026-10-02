import { FormEvent, useState } from "react";
import { api } from "../api";
import { useApp } from "../store";
import { Icon } from "../ui";

const JOB_LABEL = { add: "Adding", reindex: "Re-indexing", embed: "Adding meaning search to", code: "Scanning" };

export function StatusBar({ onSignedOut }: { onSignedOut: () => void }) {
  const app = useApp();
  const { overview } = app;
  const [account, setAccount] = useState(false);
  const running = overview.jobs.active.find((j) => j.status === "running");
  const waiting = overview.jobs.active.length - (running ? 1 : 0);
  const collection = overview.collections.find((c) => c.id === app.collectionId);

  const signOut = async () => {
    await app.run(api.post("/session/logout"));
    onSignedOut();
  };

  return (
    <footer className="status-bar">
      {running ? (
        <span className="status-job" title={running.stage}>
          <progress value={running.total ? running.done / running.total : undefined} max={1} />
          {JOB_LABEL[running.kind]} {running.name}
          {running.total > 0 && `: ${running.stage.toLowerCase()} ${running.done.toLocaleString()} of ${running.total.toLocaleString()}`}
          {waiting > 0 && ` (+${waiting} waiting)`}
        </span>
      ) : (
        <span>{overview.documents.length} document{overview.documents.length === 1 ? "" : "s"} ·{" "}
          {overview.codebases.length} codebase{overview.codebases.length === 1 ? "" : "s"}</span>
      )}
      <span className="spacer" />
      <label className="status-collection" title="Pins are added to this collection">
        <Icon name="pin" size={13} /> Pin to
        <select value={app.collectionId} onChange={(e) => app.setCollectionId(Number(e.target.value))}>
          {overview.collections.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.pin_count})</option>)}
        </select>
      </label>
      {collection && <span className="muted">{collection.pin_count} pinned</span>}
      <div className="popover-anchor">
        <button type="button" className="status-button" onClick={() => setAccount((open) => !open)}>
          <Icon name="user" size={14} /> Account
        </button>
        {account && <Account onClose={() => setAccount(false)} onSignOut={signOut} />}
      </div>
    </footer>
  );
}

function Account({ onClose, onSignOut }: { onClose: () => void; onSignOut: () => void }) {
  const app = useApp();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");

  const change = async (event: FormEvent) => {
    event.preventDefault();
    try {
      await api.post("/session/password", { current, new: next, confirm });
      app.notify("Password changed. Other browsers were signed out.");
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="popover up">
      <form onSubmit={change}>
        <strong>Change password</strong>
        <label>Current password
          <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" />
        </label>
        <label>New password
          <input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" />
        </label>
        <label>Confirm new password
          <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />
        </label>
        {error && <div className="notice error">{error}</div>}
        <button type="submit" disabled={!current || !next}>Change password</button>
      </form>
      <hr />
      <button type="button" onClick={onSignOut}>Sign out</button>
    </div>
  );
}
