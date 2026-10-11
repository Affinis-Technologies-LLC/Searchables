import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { defineConfig } from "vite";

// The build goes where the Python server serves it from. While developing ("npm run dev"), API calls
// are passed on to the server, started separately with: python -m src.server
const version = readFileSync(join(__dirname, "..", "VERSION"), "utf8").trim();

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(version),                       // From the VERSION file at the top of the repository
    __BUILD_TIME__: JSON.stringify(new Date().toISOString().slice(0, 16).replace("T", " ")),
  },
  build: {
    outDir: "../src/server/static",
    emptyOutDir: true,
    target: "es2022",
    chunkSizeWarningLimit: 4000,
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8501" },
    fs: { allow: [".", "../docs/help"] },   // The help pages are bundled from the repository's docs
  },
});
