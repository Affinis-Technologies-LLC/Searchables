// The editors open in the Code view, by file id, so the Examples view can insert into the one being written in.
import * as monaco from "monaco-editor/esm/vs/editor/edcore.main";

const editors = new Map<number, monaco.editor.IStandaloneCodeEditor>();

export function registerEditor(fileId: number, editor: monaco.editor.IStandaloneCodeEditor): () => void {
  editors.set(fileId, editor);
  return () => { if (editors.get(fileId) === editor) editors.delete(fileId); };
}

/** Puts text at the cursor of the file's editor, keeping the indentation of the current line. Returns whether it could. */
export function insertAtCursor(fileId: number, text: string): boolean {
  const editor = editors.get(fileId);
  const position = editor?.getPosition();
  const model = editor?.getModel();
  if (!editor || !position || !model) return false;
  const indent = model.getLineContent(position.lineNumber).match(/^\s*/)?.[0] ?? "";
  const lines = text.split("\n");
  const body = lines.map((line, i) => (i ? indent + line.replace(/^\s+/, "") : line)).join("\n");
  const range = new monaco.Range(position.lineNumber, position.column, position.lineNumber, position.column);
  editor.executeEdits("searchables.insert", [{ range, text: body, forceMoveMarkers: true }]);
  editor.focus();
  return true;
}
