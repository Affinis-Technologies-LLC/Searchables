// The Examples view (ADR-012): what's being written, and real statements of the codebase that do the
// same kind of thing, with why each was chosen and Preview · Go · Insert.
import { useState, useSyncExternalStore } from "react";
import { api } from "../api";
import { useApp } from "../store";
import { Example } from "../types";
import { Badge, Empty, Status } from "../ui";
import { assistant } from "./assistant";
import { insertAtCursor } from "./editors";
import { loadFile } from "./files";

const FEATURES: Record<string, string> = { T: "type", M: "member", C: "context", P: "shape", Q: "quality" };

export function ExamplesPanel() {
  const app = useApp();
  const state = useSyncExternalStore((l) => assistant.subscribe(l), () => assistant.snapshot());
  const answer = state.answer;
  const examples = assistant.visible();
  const [open, setOpen] = useState<number | null>(null);   // The example whose whole method is shown
  const [method, setMethod] = useState<{ ref: number; lines: string[]; first: number } | null>(null);

  const feedback = (example: Example, action: string) => {
    if (answer) api.post("/code/feedback", { digest: answer.context.digest, ref_id: example.ref_id, action }).catch(() => {});
  };
  const preview = async (example: Example) => {
    if (open === example.ref_id) { setOpen(null); return; }
    feedback(example, "preview");
    setOpen(example.ref_id);
    const detail = await loadFile(example.file_id).catch(() => null);
    const symbol = detail?.outline.find((s) => s.id === example.enclosing_id);
    if (detail && symbol) setMethod({ ref: example.ref_id, lines: detail.text.split("\n").slice(symbol.line - 1, symbol.end_line), first: symbol.line });
    else setMethod({ ref: example.ref_id, lines: example.lines, first: example.first_line });
  };
  const go = (example: Example) => {
    feedback(example, "go");
    app.openCode({ fileId: example.file_id, path: example.path, line: example.line });
  };
  const insert = (example: Example) => {
    if (!answer) return;
    feedback(example, "insert");
    if (!insertAtCursor(answer.context.file_id, example.statement.replace(/^\s+/, ""))) app.notify("Open the file in the editor to insert into it.", "error");
  };

  if (state.status === "idle") {
    return <Empty>Start typing in the editor. Examples from this codebase that do the same kind of thing appear here,
      with why each was chosen. Nothing is generated: every example is code that exists.</Empty>;
  }
  const context = answer?.context;
  const expression = context?.expression;
  const described = expression && expression.kind !== "none"
    ? `${expression.receiver ? expression.receiver + "." : ""}${expression.name || expression.partial || "…"}${expression.kind === "new" ? " (new)" : ""}`
    : "";
  return (
    <>
      <Status loading={state.status === "loading" && !answer} error={state.error} />
      {context && (
        <div className="context-line">
          {described ? <code>{described}</code> : <span className="muted">Nothing being written at the cursor</span>}
          {context.receiver_type && <span className="muted"> on <b>{context.receiver_type.qualified.split(/[.#]/).filter(Boolean).pop()}</b> ({context.receiver_type.certainty})</span>}
          {expression?.receiver && !context.receiver_type && <span className="muted"> — receiver not resolved</span>}
          {context.enclosing && <span className="muted"> · in {context.enclosing.qualified.split(".").pop()}</span>}
        </div>
      )}
      {answer && (
        <div className="summary">
          <span>{answer.examples.length} example{answer.examples.length === 1 ? "" : "s"} · {answer.filter}</span>
          {answer.by_name && <Badge kind="name">by name</Badge>}
        </div>
      )}
      {answer && !answer.examples.length && described && <Empty>No call like this elsewhere in the codebase.</Empty>}
      {examples.map((example) => (
        <article key={example.ref_id} className="card example">
          <header>
            <span className="card-title" title={example.enclosing}>{example.path.split("/").pop()} · {example.enclosing.split("#").pop() || "top level"}</span>
            <span className="muted score" title={Object.entries(example.features).map(([k, v]) => `${FEATURES[k] ?? k} ${v}`).join(" · ")}>{example.score.toFixed(2)}</span>
          </header>
          <div className="card-path">{example.reason}</div>
          <pre className="snippet">{(open === example.ref_id && method?.ref === example.ref_id ? method.lines : example.lines).map((text, i) => {
            const number = (open === example.ref_id && method?.ref === example.ref_id ? method.first : example.first_line) + i;
            return <div key={number} className={number >= example.start && number <= example.end ? "hit" : ""}><span className="ln">{number}</span>{text}</div>;
          })}</pre>
          <div className="row">
            <button type="button" onClick={() => preview(example)}>{open === example.ref_id ? "Less" : "Preview"}</button>
            <button type="button" onClick={() => go(example)}>Go</button>
            <button type="button" onClick={() => insert(example)} title="Insert the statement at the cursor, as written">Insert</button>
            <span className="grow" />
            <button type="button" className="quiet" onClick={() => { feedback(example, "dismiss"); assistant.dismiss(example.ref_id); }} title="Hide this example for this context">Dismiss</button>
          </div>
        </article>
      ))}
      {assistant.hiddenCount() > 0 && <button type="button" onClick={() => assistant.showMore()}>Show {assistant.hiddenCount()} more</button>}
    </>
  );
}
