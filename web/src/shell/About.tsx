// About (ADR-016): what a bug report needs, with a Copy button for the technical lines.
import { useEffect, useState } from "react";
import { api } from "../api";
import licences from "../generated/licences.json";
import { About as AboutInfo } from "../types";
import { CopyButton, Status } from "../ui";

export function About({ onClose }: { onClose: () => void }) {
  const [info, setInfo] = useState<AboutInfo | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.get<AboutInfo>("/about").then(setInfo).catch((e) => setError(e.message));
  }, []);
  const build = `${__APP_VERSION__} (built ${__BUILD_TIME__})`;
  const stale = info && info.version !== __APP_VERSION__;
  const lines = info ? [
    `Searchables ${info.version}${info.commit ? ` (${info.commit}${info.checkout ? "" : ", no checkout"})` : ""}`,
    `Interface build ${build}${stale ? " — differs from the server's version" : ""}`,
    `Python ${info.python} · ${info.platform}`,
    `Library: ${info.data_dir}`,
    `Meaning model: ${info.model.name} @ ${info.model.revision} in ${info.model.dir} — ${info.model.present ? "present" : "not downloaded"} (${info.model.device})`,
    `OCR: ${info.ocr ? "available" : "not available"}`,
    `${info.counts.documents} documents · ${info.counts.codebases} codebases · ${info.counts.collections} collections · ${info.counts.pins} pins`,
  ] : [];
  return (
    <div className="dialog-backdrop" onClick={onClose} role="presentation">
      <div className="dialog" role="dialog" aria-label="About Searchables" onClick={(e) => e.stopPropagation()}>
        <header className="row"><strong className="grow">About Searchables</strong>
          {info && <CopyButton title="Copy these lines for a bug report" text={() => lines.join("\n")} />}
          <button type="button" onClick={onClose}>Close</button></header>
        <Status loading={!info && !error} error={error} />
        {info && (
          <>
            <pre className="snippet about-lines">{lines.join("\n")}</pre>
            {stale && <div className="notice">The interface was built from version {__APP_VERSION__} but the server is {info.version}: rebuild the interface (cd web && npm run build) or pull the built one.</div>}
            <p className="muted">A local research tool for standards PDFs and source code. No AI: nothing is generated. Nothing leaves this
              machine. Nothing of the codebase is run; git is the one program it starts, for status, diff, log, blame, show and commit. See Help (F1) for what each view does.</p>
            <details>
              <summary>Bundled software and licences</summary>
              <table className="about-table">
                <tbody>
                  {licences.map((l) => <tr key={l.name}><td>{l.name}</td><td>{l.version}</td><td>{l.licence}</td></tr>)}
                  {info.python_packages.map((p) => <tr key={"py-" + p.name}><td>{p.name}</td><td>{p.version}</td><td>{p.licence}</td></tr>)}
                </tbody>
              </table>
            </details>
          </>
        )}
      </div>
    </div>
  );
}
