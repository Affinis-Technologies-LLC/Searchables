// Rename a symbol with a preview (ADR-015): every place the name would change, chosen one by one.
import { useState } from "react";
import { api } from "../api";
import { useApp } from "../store";
import { CodeSymbol, RenamePreview, RenameResult } from "../types";
import { shortPath, Status } from "../ui";
import { forgetFiles } from "./files";

const LABEL: Record<string, string> = { declaration: "Declaration", resolved: "Linked", supertype: "Through a supertype", name: "By name only (check)" };

export function RenameDialog({ symbol, onClose }: { symbol: CodeSymbol; onClose: () => void }) {
  const app = useApp();
  const [name, setName] = useState(symbol.name);
  const [preview, setPreview] = useState<RenamePreview | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [renameFile, setRenameFile] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = async () => {
    setBusy(true); setError("");
    try {
      const p = await api.post<RenamePreview>(`/code/symbols/${symbol.id}/rename/preview`, { name });
      setPreview(p);
      setChosen(new Set(p.edits.filter((e) => e.selected).map((e) => e.key)));
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  const apply = async () => {
    setBusy(true);
    try {
      const result = await api.post<RenameResult>(`/code/symbols/${symbol.id}/rename`, { name, edits: [...chosen], rename_file: renameFile && !!preview?.file_rename });
      forgetFiles();
      app.filesChanged();
      app.notify(`Renamed in ${result.files.length} file${result.files.length === 1 ? "" : "s"} (${result.edits_applied} places)${result.renamed_file ? `; file renamed to ${shortPath(result.renamed_file, 1)}` : ""}${result.skipped.length ? `; ${result.skipped.length} skipped: ${result.skipped[0].reason}` : ""}.`);
      app.setSymbolId(null);
      onClose();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  const groups = ["declaration", "resolved", "supertype", "name"];
  return (
    <div className="dialog-backdrop" onClick={onClose} role="presentation">
      <div className="dialog" role="dialog" aria-label="Rename symbol" onClick={(e) => e.stopPropagation()}>
        <header className="row"><strong className="grow">Rename {symbol.qualified.split(".").pop()}</strong><button type="button" onClick={onClose}>Close</button></header>
        <div className="row">
          <input type="text" className="grow" value={name} onChange={(e) => setName(e.target.value)} aria-label="New name" autoFocus
                 onKeyDown={(e) => { if (e.key === "Enter") load(); }} />
          <button type="button" disabled={busy || !name.trim() || name === symbol.name} onClick={load}>Preview</button>
        </div>
        <Status loading={busy && !preview} error={error} />
        {preview && (
          <>
            {preview.collision && (
              <div className="notice error">
                <code>{name}</code> exists already: <code>{preview.collision.qualified}</code> ({shortPath(preview.collision.path, 2)}:{preview.collision.line}). Choose another name.
              </div>
            )}
            {preview.also.length > 0 && <div className="notice">Renamed together: {preview.also.map((s) => s.qualified.split(".").pop() + (s.kind === "constructor" ? " (constructor)" : "")).join(", ")}</div>}
            {preview.file_rename && (
              <label className="row line check">
                <input type="checkbox" checked={renameFile} onChange={(e) => setRenameFile(e.target.checked)} />
                <span>Also rename the file <code>{shortPath(preview.file_rename[0], 1)}</code> → <code>{shortPath(preview.file_rename[1], 1)}</code></span>
              </label>
            )}
            {groups.map((g) => {
              const edits = preview.edits.filter((e) => e.certainty === g);
              if (!edits.length) return null;
              return (
                <div key={g} className="group">
                  <div className="group-title">{LABEL[g]} · {edits.length}</div>
                  {edits.map((e) => (
                    <label key={e.key} className="row line check">
                      <input type="checkbox" checked={chosen.has(e.key)} onChange={() => setChosen((c) => { const n = new Set(c); if (!n.delete(e.key)) n.add(e.key); return n; })} />
                      <span className="where">{shortPath(e.path, 2)}:{e.line}</span><code>{e.text.trim()}</code>
                    </label>
                  ))}
                </div>
              );
            })}
            {preview.mentions.length > 0 && (
              <div className="group">
                <div className="group-title">Mentioned in strings · {preview.mentions.length}</div>
                <div className="muted">Text that contains the old name, found by search, not by a link. Not changed; check them yourself.</div>
                {preview.mentions.map((m) => (
                  <button key={m.key} type="button" className="code-row usage" onClick={() => app.openCode({ fileId: m.file_id, path: m.path, line: m.line })}>
                    <span className="where">{shortPath(m.path, 2)}:{m.line}</span><code>{m.text.trim()}</code>
                  </button>
                ))}
              </div>
            )}
            <div className="row">
              <button type="button" disabled={busy || !chosen.size || !!preview.collision} onClick={apply}>Rename {chosen.size} place{chosen.size === 1 ? "" : "s"}</button>
              <span className="muted">Only the places ticked change; a place whose text moved is skipped, not guessed.</span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
