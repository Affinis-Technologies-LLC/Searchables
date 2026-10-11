// The editor without its bundled language services: this app answers "go to definition" and "hover"
// from its own code index, so only the editor core and syntax colouring are loaded.
declare module "monaco-editor/esm/vs/editor/edcore.main" {
  export * from "monaco-editor/esm/vs/editor/editor.api";
}
declare module "monaco-editor/esm/vs/basic-languages/*";

// Stamped by the build (vite.config.ts) from the VERSION file and the clock
declare const __APP_VERSION__: string;
declare const __BUILD_TIME__: string;
