// The licences of the front end's bundled dependencies, written for the About view (ADR-016).
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const own = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
const licences = Object.keys(own.dependencies).sort().map((name) => {
  const info = JSON.parse(readFileSync(join(root, "node_modules", name, "package.json"), "utf8"));
  return { name, version: info.version, licence: typeof info.license === "string" ? info.license : info.license?.type ?? "" };
});
mkdirSync(join(root, "src", "generated"), { recursive: true });
writeFileSync(join(root, "src", "generated", "licences.json"), JSON.stringify(licences, null, 2) + "\n");
