import * as monaco from "monaco-editor/esm/vs/editor/edcore.main";
import "monaco-editor/esm/vs/basic-languages/java/java.contribution";
import "monaco-editor/esm/vs/basic-languages/javascript/javascript.contribution";
import "monaco-editor/esm/vs/basic-languages/typescript/typescript.contribution";
import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import { useEffect, useRef } from "react";
import { api } from "../api";
import { CodeTab, useApp } from "../store";
import { At } from "../types";
import { Status } from "../ui";
import { useFile } from "./files";

(self as unknown as { MonacoEnvironment: object }).MonacoEnvironment = { getWorker: () => new EditorWorker() };

const LANGUAGES = ["java", "javascript", "typescript"];

function lookUp(fileId: number, position: monaco.IPosition): Promise<At> {
  return api.get<At>(`/code/files/${fileId}/at?line=${position.lineNumber}&col=${position.column}`);
}

function fileOf(model: monaco.editor.ITextModel): number {
  return Number(model.uri.path.split("/")[1]);
}

// Hovering a name shows what it refers to, answered by the code index
let hoverRegistered = false;
function registerHover(): void {
  if (hoverRegistered) return;
  hoverRegistered = true;
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

/** A source file in a read-only editor: F12 or Ctrl/Cmd+click goes to a declaration, the cursor drives the inspector. */
export function CodeView({ tab, visible }: { tab: CodeTab; visible: boolean }) {
  const app = useApp();
  const { data, loading, error } = useFile(tab.fileId);
  const host = useRef<HTMLDivElement>(null);
  const editor = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  const marks = useRef<monaco.editor.IEditorDecorationsCollection | null>(null);
  const actions = useRef(app);
  actions.current = app;

  useEffect(() => {
    if (!data || !host.current) return;
    registerHover();
    const uri = monaco.Uri.parse(`file:///${data.file.id}/${data.file.path}`);
    monaco.editor.getModel(uri)?.dispose();
    const model = monaco.editor.createModel(data.text, data.file.language, uri);
    const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const instance = monaco.editor.create(host.current, {
      model, readOnly: true, domReadOnly: true, automaticLayout: true, theme: dark ? "vs-dark" : "vs",
      fontSize: 13, scrollBeyondLastLine: false, renderLineHighlight: "all", occurrencesHighlight: "singleFile",
      minimap: { enabled: true }, stickyScroll: { enabled: true }, links: false,
    });
    editor.current = instance;
    marks.current = instance.createDecorationsCollection();

    const follow = async (position: monaco.IPosition | null) => {
      if (!position) return;
      const at = await lookUp(data.file.id, position).catch(() => null);
      const app = actions.current;
      if (!at) return;
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
      instance.dispose();
      model.dispose();
      editor.current = null;
    };
  }, [data]);

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
        <span className="grow path" title={tab.path}>{tab.path}</span>
        {data && <span className="muted">{data.file.lines.toLocaleString()} lines · {data.file.language}
          {data.file.has_errors && " · has syntax the parser couldn't fully read"}</span>}
        <span className="muted hint"><kbd>F12</kbd> or <kbd>Ctrl</kbd>+click: go to definition · <kbd>Shift</kbd>+<kbd>F12</kbd>: usages</span>
      </div>
      <Status loading={loading && !data} error={error} />
      <div className="code-host" ref={host} />
    </div>
  );
}
