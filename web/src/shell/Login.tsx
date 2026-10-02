import { FormEvent, useState } from "react";
import { api } from "../api";

export interface SessionInfo { authenticated: boolean; setup: boolean; min_password: number; idle_minutes: number; auth_file: string }

/** The first-run "create a password" page, and the sign-in page after that. */
export function Login({ session, onSignedIn }: { session: SessionInfo; onSignedIn: () => void }) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await (session.setup ? api.post("/session/setup", { password, confirm }) : api.post("/session/login", { password }));
      onSignedIn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="center">
      <form className="login" onSubmit={submit}>
        <h1>Searchables</h1>
        <h2>{session.setup ? "Create a password" : "Sign in"}</h2>
        {session.setup && (
          <p className="hint">Choose a password of at least {session.min_password} characters. You'll need it each time
            you open the app. It's stored only as a secure hash on this machine.</p>
        )}
        <label>Password
          <input type="password" value={password} autoFocus onChange={(e) => setPassword(e.target.value)}
                 autoComplete={session.setup ? "new-password" : "current-password"} />
        </label>
        {session.setup && (
          <label>Confirm password
            <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />
          </label>
        )}
        {error && <div className="notice error">{error}</div>}
        <button className="primary" type="submit" disabled={busy || !password}>
          {session.setup ? "Create password and continue" : "Sign in"}
        </button>
        {!session.setup && (
          <p className="hint">Forgotten it? Delete <code>{session.auth_file}</code> and restart the app to set a new
            one. Your documents and collections are kept.</p>
        )}
      </form>
    </div>
  );
}
