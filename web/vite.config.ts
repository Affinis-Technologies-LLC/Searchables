import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The build goes where the Python server serves it from. While developing ("npm run dev"), API calls
// are passed on to the server, started separately with: python -m src.server
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/server/static",
    emptyOutDir: true,
    target: "es2022",
    chunkSizeWarningLimit: 4000,
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8501" },
  },
});
