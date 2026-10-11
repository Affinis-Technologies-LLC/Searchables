// A small Markdown reader for the help pages (ADR-016): headings, paragraphs, lists, code blocks,
// emphasis, inline code and links. Links to other pages end in ".md"; links into the app start
// with "app:". Nothing else is needed for help, so nothing else is read.

export type Span =
  | { kind: "text"; text: string }
  | { kind: "em"; text: string }
  | { kind: "strong"; text: string }
  | { kind: "code"; text: string }
  | { kind: "kbd"; text: string }
  | { kind: "link"; text: string; href: string };

export type Block =
  | { type: "heading"; level: number; text: string; id: string }
  | { type: "paragraph"; spans: Span[] }
  | { type: "list"; ordered: boolean; items: Span[][] }
  | { type: "code"; text: string };

export function slug(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

/** Inline marks, left to right: `code`, **strong**, *em*, [text](href). Backticks around a key name make a kbd. */
export function spans(text: string): Span[] {
  const out: Span[] = [];
  const pattern = /`([^`]+)`|\*\*([^*]+)\*\*|\*([^*]+)\*|\[([^\]]+)\]\(([^)]+)\)/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index! > last) out.push({ kind: "text", text: text.slice(last, match.index) });
    if (match[1] !== undefined) out.push(/^(F\d{1,2}|Ctrl|Cmd|Alt|Shift|Enter|Esc|Escape|Space|Tab|[←→↑↓]|[A-Z])$/.test(match[1]) ? { kind: "kbd", text: match[1] } : { kind: "code", text: match[1] });
    else if (match[2] !== undefined) out.push({ kind: "strong", text: match[2] });
    else if (match[3] !== undefined) out.push({ kind: "em", text: match[3] });
    else out.push({ kind: "link", text: match[4], href: match[5] });
    last = match.index! + match[0].length;
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
  return out;
}

export function parse(markdown: string): Block[] {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    const heading = line.match(/^(#{1,3}) (.+)$/);
    if (heading) {
      blocks.push({ type: "heading", level: heading[1].length, text: heading[2].trim(), id: slug(heading[2]) });
      i++;
      continue;
    }
    if (line.startsWith("```")) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) code.push(lines[i++]);
      i++;
      blocks.push({ type: "code", text: code.join("\n") });
      continue;
    }
    const item = line.match(/^(\s*)([-*]|\d+\.) (.*)$/);
    if (item) {
      const ordered = /\d/.test(item[2]);
      const items: string[] = [];
      while (i < lines.length) {
        const next = lines[i].match(/^(\s*)([-*]|\d+\.) (.*)$/);
        if (next && /\d/.test(next[2]) === ordered) { items.push(next[3]); i++; continue; }
        if (lines[i].match(/^\s{2,}\S/) && items.length) { items[items.length - 1] += " " + lines[i].trim(); i++; continue; }
        break;
      }
      blocks.push({ type: "list", ordered, items: items.map(spans) });
      continue;
    }
    const paragraph: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,3} |```|\s*([-*]|\d+\.) )/.test(lines[i])) paragraph.push(lines[i++].trim());
    blocks.push({ type: "paragraph", spans: spans(paragraph.join(" ")) });
  }
  return blocks;
}

/** The plain text and the links of a paragraph or list, for tests and search. */
export function textOf(block: Block): { text: string; links: string[] } {
  const all: Span[] = block.type === "paragraph" ? block.spans : block.type === "list" ? block.items.flat() : [];
  return { text: block.type === "heading" || block.type === "code" ? block.text : all.map((s) => s.text).join(""),
           links: all.filter((s): s is Extract<Span, { kind: "link" }> => s.kind === "link").map((s) => s.href) };
}

export interface HelpHit { page: string; title: string; snippet: string }

/** Pages containing every word of the query, best first, with a snippet around the first word. */
export function searchPages(pages: Record<string, string>, query: string): HelpHit[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const hits: (HelpHit & { count: number })[] = [];
  for (const [page, markdown] of Object.entries(pages)) {
    const text = parse(markdown).map((b) => textOf(b).text).join("\n");
    const lower = text.toLowerCase();
    if (!words.every((w) => lower.includes(w))) continue;
    const count = words.reduce((n, w) => n + lower.split(w).length - 1, 0);
    const at = lower.indexOf(words[0]);
    const start = Math.max(0, text.lastIndexOf("\n", at) + 1);
    const end = text.indexOf("\n", at);
    const snippet = text.slice(start, end === -1 ? undefined : end).trim();
    hits.push({ page, title: markdown.split("\n")[0].replace(/^# /, ""), snippet: snippet.length > 160 ? snippet.slice(0, 157) + "…" : snippet, count });
  }
  return hits.sort((a, b) => b.count - a.count || a.title.localeCompare(b.title)).map(({ count: _, ...hit }) => hit);
}
