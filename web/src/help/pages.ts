// The help pages, bundled from docs/help at build time so they're offline and match the build.
const files = import.meta.glob("../../../docs/help/*.md", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

export const pages: Record<string, string> = Object.fromEntries(
  Object.entries(files).map(([path, text]) => [path.split("/").pop()!.replace(/\.md$/, ""), text]),
);

export function titleOf(page: string): string {
  return pages[page]?.split("\n")[0].replace(/^# /, "") ?? page;
}

/** The order pages are listed in: the overview first, then the views in the activity bar's order. */
export const ORDER = ["help", "search", "contents", "catalogue", "glossary", "compare", "collections", "code", "library"];
