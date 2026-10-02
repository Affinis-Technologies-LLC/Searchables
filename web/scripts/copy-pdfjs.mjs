// PDF.js loads character maps and the standard 14 fonts at run time, for PDFs that don't embed their
// own. They're copied next to the app so nothing is fetched from the internet.
import { cpSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const target = join(root, "public", "pdfjs");
rmSync(target, { recursive: true, force: true });
for (const folder of ["cmaps", "standard_fonts"]) {
  cpSync(join(root, "node_modules", "pdfjs-dist", folder), join(target, folder), { recursive: true });
}
