import { DragEvent, useRef, useState } from "react";
import { api } from "../api";
import { useLoad } from "../hooks";
import { useApp } from "../store";
import { DocumentInfo, IdentifierFamily, Job } from "../types";
import { Empty, Icon, Status } from "../ui";

const JOB_LABEL = { add: "Adding", reindex: "Re-indexing", embed: "Adding meaning search to", code: "Scanning" };

/** Add PDFs and manage the library: rename, re-index, delete, and each document's identifier patterns. */
export function LibraryPanel() {
  const app = useApp();
  const { overview } = app;
  const picker = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);

  const add = async (files: FileList | File[]) => {
    for (const file of Array.from(files)) {
      if (!file.name.toLowerCase().endsWith(".pdf")) {
        app.notify(`${file.name} isn't a PDF.`, "error");
        continue;
      }
      await app.run(api.upload(`/documents?filename=${encodeURIComponent(file.name)}`, file));
    }
    app.refresh();
  };
  const drop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    add(event.dataTransfer.files);
  };
  const queue = async (docs: DocumentInfo[], action: "reindex" | "embed") => {
    for (const doc of docs) await app.run(api.post(`/documents/${doc.id}/${action}`));
    app.refresh();
  };

  const outdated = overview.documents.filter((d) => d.outdated && !d.busy);
  const withoutMeaning = overview.documents.filter((d) => !d.outdated && !d.meaning && !d.busy);
  return (
    <div className="panel">
      <div className="panel-head">
        <div className={`dropzone ${dragging ? "over" : ""}`} onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
             onDragLeave={() => setDragging(false)} onDrop={drop} onClick={() => picker.current?.click()} role="button" tabIndex={0}>
          <Icon name="plus" /> Add PDFs: drop them here, or click to choose
          <input ref={picker} type="file" accept="application/pdf,.pdf" multiple hidden
                 onChange={(e) => { if (e.target.files) add(e.target.files); e.target.value = ""; }} />
        </div>
      </div>
      <div className="panel-body">
        {!overview.ocr && (
          <div className="notice">Tesseract OCR was not found, so scanned pages can't be read. Install it and restart the app
            (see the README for your system).</div>
        )}
        {outdated.length > 0 && (
          <div className="notice">
            {outdated.length} document{outdated.length === 1 ? " was" : "s were"} indexed by an older version and
            {outdated.length === 1 ? " is" : " are"} missing newer features.
            <button type="button" className="primary" onClick={() => queue(outdated, "reindex")}>Re-index {outdated.length === 1 ? "it" : "them"}</button>
          </div>
        )}
        {withoutMeaning.length > 0 && (
          <div className="notice">
            {withoutMeaning.length} document{withoutMeaning.length === 1 ? "" : "s"} can't be searched by meaning yet.
            <button type="button" onClick={() => queue(withoutMeaning, "embed")}>Add meaning search</button>
          </div>
        )}
        <Jobs active={overview.jobs.active} finished={overview.jobs.finished} />

        {!overview.documents.length && <Empty>No documents yet.</Empty>}
        {overview.documents.map((doc) => (
          <DocumentRow key={doc.id} doc={doc} expanded={expanded === doc.id}
                       onToggle={() => setExpanded(expanded === doc.id ? null : doc.id)} onQueue={queue} />
        ))}
      </div>
    </div>
  );
}

function Jobs({ active, finished }: { active: Job[]; finished: Job[] }) {
  if (!active.length && !finished.length) return null;
  return (
    <section className="jobs">
      <div className="group-title">Indexing</div>
      {active.map((job) => (
        <div key={job.id} className="job">
          {job.status === "running"
            ? <>
                <progress value={job.total ? job.done / job.total : undefined} max={1} />
                <span>{JOB_LABEL[job.kind]} {job.name}: {job.total
                  ? `${job.stage.toLowerCase()} ${job.done.toLocaleString()} of ${job.total.toLocaleString()}`
                  : "starting (loading the language model the first time)…"}</span>
              </>
            : <span className="muted">Waiting: {JOB_LABEL[job.kind].toLowerCase()} {job.name}</span>}
        </div>
      ))}
      {[...finished].reverse().slice(0, 5).map((job) => (
        <div key={job.id}>
          <div className={`notice ${job.status === "failed" ? "error" : "ok"}`}>{job.status === "failed" ? `${job.name}: ${job.result}` : job.result}</div>
          {job.warning && <div className="notice">{job.warning}</div>}
        </div>
      ))}
    </section>
  );
}

function DocumentRow({ doc, expanded, onToggle, onQueue }: {
  doc: DocumentInfo; expanded: boolean; onToggle: () => void; onQueue: (docs: DocumentInfo[], action: "reindex" | "embed") => void;
}) {
  const app = useApp();
  const [title, setTitle] = useState(doc.title);
  const rename = async () => {
    if (title.trim() && title.trim() !== doc.title && await app.run(api.patch(`/documents/${doc.id}`, { title }))) app.refresh();
  };
  const remove = async () => {
    if (window.confirm(`Remove “${doc.title}” and its index from the library? Pins keep their text and citation.`)) {
      await app.run(api.del(`/documents/${doc.id}`));
      app.close(`doc:${doc.id}`);
      app.refresh();
    }
  };
  return (
    <article className="card static">
      <header>
        <button type="button" className="link card-title" onClick={() => app.openDoc({ docId: doc.id, page: 1 })} title="Open">{doc.title}</button>
        <span className="grow" />
        <button type="button" onClick={onToggle} aria-expanded={expanded}>{expanded ? "Close" : "Manage"}</button>
      </header>
      <div className="card-path">
        {doc.page_count.toLocaleString()} pages · {doc.block_count.toLocaleString()} passages
        {doc.ocr_pages > 0 && ` · ${doc.ocr_pages} read with OCR`} · meaning search {doc.meaning ? "on" : doc.busy ? "being added" : "not yet"}
        {doc.busy && " · indexing"}
      </div>
      {expanded && (
        <div className="manage">
          <div className="muted">{doc.filename} · added {doc.added_at.replace("T", " ")}</div>
          <div className="row">
            <input className="grow" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Title" />
            <button type="button" disabled={!title.trim() || title.trim() === doc.title} onClick={rename}>Save title</button>
          </div>
          <div className="row">
            <button type="button" disabled={doc.busy} onClick={() => onQueue([doc], "reindex")}
                    title="Re-extract from the stored PDF (runs in the background)"><Icon name="refresh" size={13} /> Re-index</button>
            <button type="button" disabled={doc.busy} onClick={remove}><Icon name="trash" size={13} /> Delete…</button>
          </div>
          <Families doc={doc} />
        </div>
      )}
    </article>
  );
}

function Families({ doc }: { doc: DocumentInfo }) {
  const app = useApp();
  const { data, loading, error, reload } = useLoad<IdentifierFamily[]>(() => api.get(`/documents/${doc.id}/identifiers`), [doc.id, doc.block_count]);
  const set = async (body: object) => { await app.run(api.put(`/documents/${doc.id}/identifiers`, body)); reload(); };
  return (
    <>
      <div className="group-title">Identifiers</div>
      <div className="muted">Patterns discovered from the document (# stands for any number). Switch them on or off; your choices are kept when it's re-indexed.</div>
      <Status loading={loading && !data} error={error} />
      {data && !data.length && <div className="muted">No identifier-like patterns found in this document.</div>}
      {data && data.length > 0 && (
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>Use</th><th>Pattern</th><th>Values</th><th>Passages</th><th>Examples</th><th>Setting</th></tr></thead>
            <tbody>
              {data.map((family) => (
                <tr key={family.family}>
                  <td><input type="checkbox" checked={family.enabled} aria-label={`Use ${family.display}`}
                             // Matching discovery's own verdict returns the pattern to automatic
                             onChange={(e) => set({ family: family.family, enabled: e.target.checked === family.auto_enabled ? null : e.target.checked })} /></td>
                  <td>{family.display}</td><td>{family.distinct_values}</td><td>{family.passages}</td><td>{family.examples}</td>
                  <td>{family.user_enabled === null ? "automatic" : "your choice"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data?.some((f) => f.user_enabled !== null) && <button type="button" onClick={() => set({})}>Reset all to automatic</button>}
    </>
  );
}
