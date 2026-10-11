import * as monaco from "monaco-editor/esm/vs/editor/edcore.main";
import "monaco-editor/esm/vs/basic-languages/java/java.contribution";
import "monaco-editor/esm/vs/basic-languages/javascript/javascript.contribution";
import "monaco-editor/esm/vs/basic-languages/typescript/typescript.contribution";
import "monaco-editor/esm/vs/basic-languages/html/html.contribution";   // Angular templates
import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { api } from "../api";
import { CodeTab, useApp } from "../store";
import { At, CompletionItem, ExamplesAnswer } from "../types";
import { Status } from "../ui";
import { assistant } from "./assistant";
import { drafts } from "./drafts";
import { saveFile } from "./editing";
import { registerEditor } from "./editors";
import { useFile } from "./files";

(self as unknown as { MonacoEnvironment: object }).MonacoEnvironment = { getWorker: () => new EditorWorker() };

const LANGUAGES = ["java", "javascript", "typescript", "html"];
const ASSISTED = ["java", "javascript", "typescript"];   // Examples and completion from the index (ADR-012)
const PAUSE = 400;                                        // ms after typing stops before the context is asked for

const askExamples = (fileId: number, text: string, line: number, col: number) =>
  api.post<ExamplesAnswer>(`/code/files/${fileId}/context`, { text, line, col });

function lookUp(fileId: number, position: monaco.IPosition): Promise<At> {
  return api.get<At>(`/code/files/${fileId}/at?line=${position.lineNumber}&col=${position.column}`);
}

function fileOf(model: monaco.editor.ITextModel): number {
  return Number(model.uri.path.split("/")[1]);
}

const KINDS: Record<string, monaco.languages.CompletionItemKind> = {
  method: monaco.languages.CompletionItemKind.Method, function: monaco.languages.CompletionItemKind.Function,
  field: monaco.languages.CompletionItemKind.Field, variable: monaco.languages.CompletionItemKind.Variable,
  class: monaco.languages.CompletionItemKind.Class, interface: monaco.languages.CompletionItemKind.Interface,
  enum: monaco.languages.CompletionItemKind.Enum, record: monaco.languages.CompletionItemKind.Struct,
  type: monaco.languages.CompletionItemKind.TypeParameter, api: monaco.languages.CompletionItemKind.Reference,
  import: monaco.languages.CompletionItemKind.Module,
};

/** Where an import goes: after the last import, else after the package line, else at the top. */
function importEdit(model: monaco.editor.ITextModel, item: CompletionItem): monaco.languages.TextEdit | null {
  if (!item.insert_import) return null;
  const java = model.getLanguageId() === "java";
  const statement = java ? `import ${item.insert_import};` : `import { ${item.name} } from '${item.insert_import}';`;
  let after = 0;
  for (let n = 1; n <= Math.min(model.getLineCount(), 400); n++) {
    const text = model.getLineContent(n);
    if (/^\s*import\b/.test(text) || (java && /^\s*package\b/.test(text))) after = n;
    if (text.includes(statement)) return null;   // Imported already
  }
  return { range: new monaco.Range(after + 1, 1, after + 1, 1), text: statement + "\n" + (after === 0 ? "\n" : "") };
}

// Hovering a name shows what it refers to, answered by the code index; completion comes from the index too
let hoverRegistered = false;
function registerHover(): void {
  if (hoverRegistered) return;
  hoverRegistered = true;
  for (const language of ASSISTED) {
    monaco.languages.registerCompletionItemProvider(language, {
      triggerCharacters: ["."],
      async provideCompletionItems(model, position) {
        const word = model.getWordUntilPosition(position);
        const range = new monaco.Range(position.lineNumber, word.startColumn, position.lineNumber, word.endColumn);
        const answer = await api.post<{ items: CompletionItem[] }>(`/code/files/${fileOf(model)}/complete`,
          { text: model.getValue(), line: position.lineNumber, col: position.column }).catch(() => null);
        if (!answer) return { suggestions: [] };
        return {
          suggestions: answer.items.map((item, i) => {
            const edit = importEdit(model, item);
            return {
              label: { label: item.name, detail: item.params >= 0 && item.kind !== "field" && item.kind !== "variable" ? `(${item.params})` : "",
                       description: item.examples ? `${item.examples} example${item.examples === 1 ? "" : "s"}` : item.detail },
              kind: KINDS[item.kind] ?? monaco.languages.CompletionItemKind.Text,
              insertText: item.name, range, sortText: String(i).padStart(3, "0"),
              detail: item.type || item.detail,
              documentation: item.signature ? { value: "```" + model.getLanguageId() + "\n" + item.signature + "\n```" + (edit ? `\n\nAdds \`${edit.text.trim()}\`` : "") } : undefined,
              additionalTextEdits: edit ? [edit] : undefined,
            };
          }),
        };
      },
    });
  }
  for (const language of LANGUAGES) {
    monaco.languages.registerHoverProvider(language, {
      async provideHover(model, position) {
        const at = await lookUp(fileOf(model), position).catch(() => null);
        const symbol = at?.target ?? at?.declared;
        if (symbol) {
          return { contents: [{ value: "```" + symbol.language + "\n" + symbol.signature + "\n```" },
                              { value: `${symbol.kind} · ${symbol.path}:${symbol.line}` }] };
        }
        if (at?.ref?.target) return { contents: [{ value: `Outside API: \`${at.ref.target}\`` }] };
        if (at?.candidates.length) {
          return { contents: [{ value: `Not linked for certain. ${at.candidates.length} declaration${at.candidates.length === 1 ? "" : "s"} with this name (see the inspector).` }] };
        }
        return null;
      },
    });
  }
}

/** The unsaved state of one file, as the drafts store sees it. */
export function useDraft(fileId: number) {
  return useSyncExternalStore(
    (listener) => drafts.subscribe(listener),
    () => `${drafts.isDirty(fileId) ? "dirty" : "clean"}:${drafts.conflict(fileId) ? drafts.conflict(fileId)!.currentSha : ""}`,
  );
}

/**
 * A source file in the editor: F12 or Ctrl/Cmd+click goes to a declaration, the cursor drives the
 * inspector, Ctrl/Cmd+S saves. Unsaved text lives in the drafts store, so it survives tab switches.
 */
export function CodeView({ tab, visible }: { tab: CodeTab; visible: boolean }) {
  const app = useApp();
  const { data, loading, error } = useFile(tab.fileId);
  const host = useRef<HTMLDivElement>(null);
  const editor = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  const marks = useRef<monaco.editor.IEditorDecorationsCollection | null>(null);
  const actions = useRef(app);
  actions.current = app;
  const draftState = useDraft(tab.fileId);
  const dirty = draftState.startsWith("dirty");
  const conflict = drafts.conflict(tab.fileId);
  const [saving, setSaving] = useState(false);
  const [comparing, setComparing] = useState(false);
  const fileId = data?.file.id;

  const save = async () => {
    if (saving || !drafts.isDirty(tab.fileId)) return;
    setSaving(true);
    try {
      const saved = await saveFile(tab.fileId);
      if (saved) actions.current.filesChanged();
      else if (drafts.conflict(tab.fileId)) actions.current.notify("The file has changed on disk since it was opened. Compare the two before saving.", "error");
    } catch (error) {
      actions.current.notify(error instanceof Error ? error.message : String(error), "error");
    } finally {
      setSaving(false);
    }
  };
  const saveRef = useRef(save);
  saveRef.current = save;

  useEffect(() => {
    if (!data || !host.current) return;
    registerHover();
    const uri = monaco.Uri.parse(`file:///${data.file.id}/${data.file.path}`);
    monaco.editor.getModel(uri)?.dispose();
    const draft = drafts.open(data.file.id, data.file.path, data.text, data.file.sha256);
    const model = monaco.editor.createModel(draft.text, data.file.language, uri);
    const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const assisted = ASSISTED.includes(data.file.language);
    const instance = monaco.editor.create(host.current, {
      model, readOnly: !data.editable, automaticLayout: true, theme: dark ? "vs-dark" : "vs",
      fontSize: 13, scrollBeyondLastLine: false, renderLineHighlight: "all", occurrencesHighlight: "singleFile",
      minimap: { enabled: true }, stickyScroll: { enabled: true }, links: false,
      wordBasedSuggestions: assisted ? "off" : "currentDocument",   // Completion is from the index, never from the text
      quickSuggestions: assisted ? { other: true, comments: false, strings: false } : false,
    });
    editor.current = instance;
    marks.current = instance.createDecorationsCollection();
    const unregister = registerEditor(data.file.id, instance);
    // The Examples view follows what's being written: asked for after a pause in typing or a cursor move
    let pause = 0;
    const ask = () => {
      const position = instance.getPosition();
      if (!assisted || !position) return;
      assistant.request(data.file.id, model.getValue(), position.lineNumber, position.column, askExamples);
    };
    model.onDidChangeContent(() => {
      drafts.setText(data.file.id, model.getValue());
      window.clearTimeout(pause);
      pause = window.setTimeout(ask, PAUSE);
      actions.current.setInspectorView("Examples");
    });
    instance.addAction({ id: "searchables.save", label: "Save", keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS],
                         contextMenuGroupId: "1_modification", run: () => { saveRef.current(); } });

    const follow = async (position: monaco.IPosition | null) => {
      if (!position) return;
      const at = await lookUp(data.file.id, position).catch(() => null);
      const app = actions.current;
      if (!at) return;
      if (app.inspectorView === "Examples" && (at.target || at.declared || at.candidates.length)) app.setInspectorView("Usages");
      if (at.target) {
        app.openCode({ fileId: at.target.file_id, path: at.target.path, line: at.target.line });
        app.setSymbolId(at.target.id);
        app.setAt(null);
      } else if (at.declared) {
        app.setSymbolId(at.declared.id);   // Already at the declaration: show where it's used
        app.setAt(null);
      } else if (at.candidates.length === 1) {
        const [only] = at.candidates;
        app.openCode({ fileId: only.file_id, path: only.path, line: only.line });
        app.setSymbolId(only.id);
        app.setAt(null);
      } else if (at.ref) {
        app.setAt(at);                     // An outside API, or several possible declarations: the inspector lists them
        if (!at.ref.target && !at.candidates.length) app.notify("No declaration found for this in the codebase.");
      }
    };
    instance.addAction({ id: "searchables.definition", label: "Go to Definition", keybindings: [monaco.KeyCode.F12],
                         contextMenuGroupId: "navigation", contextMenuOrder: 1, run: (ed) => { follow(ed.getPosition()); } });
    instance.addAction({ id: "searchables.usages", label: "Find Usages", keybindings: [monaco.KeyMod.Shift | monaco.KeyCode.F12],
                         contextMenuGroupId: "navigation", contextMenuOrder: 2, run: async (ed) => {
                           const position = ed.getPosition();
                           const at = position && await lookUp(data.file.id, position).catch(() => null);
                           const symbol = at?.target ?? at?.declared;
                           if (symbol || at?.ref) actions.current.setInspectorView("Usages");
                           if (symbol) { actions.current.setSymbolId(symbol.id); actions.current.setAt(null); }
                           else if (at?.ref) actions.current.setAt(at);
                         } });
    instance.onMouseDown((event) => {
      if ((event.event.ctrlKey || event.event.metaKey) && event.target.position) follow(event.target.position);
    });

    // The inspector follows the cursor: what's under it, once it has rested there
    let timer = 0;
    instance.onDidChangeCursorPosition((event) => {
      if (event.reason !== monaco.editor.CursorChangeReason.Explicit) return;
      window.clearTimeout(pause);
      pause = window.setTimeout(ask, PAUSE);
      window.clearTimeout(timer);
      timer = window.setTimeout(async () => {
        const at = await lookUp(data.file.id, event.position).catch(() => null);
        const symbol = at?.target ?? at?.declared;
        if (symbol) { actions.current.setSymbolId(symbol.id); actions.current.setAt(null); }
        else if (at?.ref) actions.current.setAt(at);
      }, 300);
    });
    return () => {
      window.clearTimeout(timer);
      window.clearTimeout(pause);
      unregister();
      instance.dispose();
      model.dispose();
      editor.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileId]);

  // The file as the server has it changed (a rescan, a replacement, a conflict resolved): the editor follows
  // unless it holds unsaved text, which then becomes a conflict to settle
  useEffect(() => {
    const model = editor.current?.getModel();
    if (!data || !model) return;
    const draft = drafts.open(data.file.id, data.file.path, data.text, data.file.sha256);
    if (model.getValue() !== draft.text) model.setValue(draft.text);
  }, [data]);
  useEffect(() => {
    const model = editor.current?.getModel();
    const text = drafts.text(tab.fileId);
    if (model && text !== undefined && model.getValue() !== text) model.setValue(text);
  }, [draftState, tab.fileId]);

  // Show the line navigated to
  useEffect(() => {
    const instance = editor.current;
    if (!instance || !data || !visible) return;
    const line = Math.min(Math.max(tab.line, 1), instance.getModel()?.getLineCount() ?? 1);
    instance.revealLineInCenter(line);
    instance.setPosition({ lineNumber: line, column: 1 });
    marks.current?.set([{ range: new monaco.Range(line, 1, line, 1),
                          options: { isWholeLine: true, className: "line-target", linesDecorationsClassName: "line-target-margin" } }]);
  }, [tab.nonce, tab.line, data, visible]);

  return (
    <div className="viewer">
      <div className="toolbar">
        <span className="grow path" title={tab.path}>{tab.path}{dirty && <span className="unsaved" title="Unsaved changes"> ●</span>}</span>
        {data && <span className="muted">{data.file.lines.toLocaleString()} lines · {data.file.language}
          {data.file.has_errors && " · has syntax the parser couldn't fully read"}</span>}
        <button type="button" disabled={!dirty || saving} onClick={save} title="Save (Ctrl/Cmd+S)">{saving ? "Saving…" : "Save"}</button>
        <span className="muted hint"><kbd>F12</kbd> or <kbd>Ctrl</kbd>+click: go to definition · <kbd>Shift</kbd>+<kbd>F12</kbd>: usages</span>
      </div>
      {conflict && data && (
        <div className="notice error" role="alert">
          <span className="grow">This file changed on disk after it was opened. Nothing was overwritten.</span>
          <button type="button" onClick={() => setComparing(!comparing)}>{comparing ? "Back to the editor" : "Compare"}</button>
          <button type="button" onClick={() => { drafts.resolve(tab.fileId, "theirs"); setComparing(false); }}>Take the version on disk</button>
          <button type="button" onClick={() => { drafts.resolve(tab.fileId, "mine"); setComparing(false); }}>Keep mine (save will overwrite)</button>
        </div>
      )}
      <Status loading={loading && !data} error={error} />
      {conflict && comparing && data && <Compare theirs={conflict.currentText} mine={drafts.text(tab.fileId) ?? ""} language={data.file.language} />}
      <div className="code-host" ref={host} hidden={!!(conflict && comparing)} />
    </div>
  );
}


// One diff editor for the whole app, moved into whichever comparison is shown: disposing a diff editor
// takes services other editors' suggest and hover widgets still use (Monaco 0.52), so it's kept.
let diffEditor: { editor: monaco.editor.IStandaloneDiffEditor; element: HTMLDivElement } | null = null;

/** The version on disk against what's in the editor, side by side. */
function Compare({ theirs, mine, language }: { theirs: string; mine: string; language: string }) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!host.current) return;
    const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    if (!diffEditor) {
      const element = document.createElement("div");
      element.style.height = "100%";
      const editor = monaco.editor.createDiffEditor(element, { readOnly: true, automaticLayout: true, theme: dark ? "vs-dark" : "vs",
                                                                fontSize: 13, renderSideBySide: true, originalEditable: false });
      diffEditor = { editor, element };
    }
    const original = monaco.editor.createModel(theirs, language);
    const modified = monaco.editor.createModel(mine, language);
    host.current.appendChild(diffEditor.element);
    diffEditor.editor.setModel({ original, modified });
    diffEditor.editor.layout();
    return () => {
      diffEditor?.editor.setModel(null);
      diffEditor?.element.remove();
      original.dispose();
      modified.dispose();
    };
  }, [theirs, mine, language]);
  return <div className="code-host" ref={host} title="On disk (left) · in the editor (right)" />;
}
