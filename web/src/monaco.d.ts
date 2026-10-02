// The editor without its bundled language services: this app answers "go to definition" and "hover"
// from its own code index, so only the editor core and syntax colouring are loaded.
declare module "monaco-editor/esm/vs/editor/edcore.main" {
  export * from "monaco-editor/esm/vs/editor/editor.api";
}
declare module "monaco-editor/esm/vs/basic-languages/*";
