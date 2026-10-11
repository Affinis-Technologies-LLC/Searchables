import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { parse, searchPages, textOf } from "./markdown";

const HELP = join(__dirname, "../../../docs/help");
const pages = Object.fromEntries(readdirSync(HELP).filter((f) => f.endsWith(".md")).map((f) => [f.slice(0, -3), readFileSync(join(HELP, f), "utf8")]));

describe("the help reader", () => {
  it("reads headings, paragraphs, lists, code, emphasis and links", () => {
    const blocks = parse("# Title\n\nA *word* and **bold** with `code` and a [link](search.md) and [view](app:catalogue).\n\n- one\n- two\n\n1. first\n2. second\n\n```\nlet x = 1;\n```\n\n## Sub\n\nText.");
    expect(blocks.map((b) => b.type)).toEqual(["heading", "paragraph", "list", "list", "code", "heading", "paragraph"]);
    const [title, para, bullets, numbered, code, sub] = blocks;
    expect(title).toMatchObject({ type: "heading", level: 1, text: "Title" });
    expect(sub).toMatchObject({ type: "heading", level: 2 });
    expect(para.type === "paragraph" && para.spans.map((s) => s.kind)).toEqual(["text", "em", "text", "strong", "text", "code", "text", "link", "text", "link", "text"]);
    expect(para.type === "paragraph" && para.spans.filter((s) => s.kind === "link").map((s) => s.kind === "link" && s.href)).toEqual(["search.md", "app:catalogue"]);
    expect(bullets).toMatchObject({ type: "list", ordered: false });
    expect(numbered).toMatchObject({ type: "list", ordered: true });
    expect(code).toMatchObject({ type: "code", text: "let x = 1;" });
  });

  it("renders every help page: a title first, every heading and link kept", () => {
    for (const [name, text] of Object.entries(pages)) {
      const blocks = parse(text);
      expect(blocks[0], name).toMatchObject({ type: "heading", level: 1 });
      const headings = text.split("\n").filter((l) => /^#{1,3} /.test(l)).length;
      expect(blocks.filter((b) => b.type === "heading").length, name).toBe(headings);
      const links = [...text.matchAll(/\]\(([^)]+)\)/g)].map((m) => m[1]);
      const kept = blocks.flatMap((b) => (b.type === "paragraph" || b.type === "list" ? textOf(b).links : []));
      expect(kept, name).toEqual(links);
    }
  });

  it("finds a page by a word from it", () => {
    const hits = searchPages(pages, "acronym");
    expect(hits.map((h) => h.page)).toContain("glossary");
    expect(hits[0].snippet.toLowerCase()).toContain("acronym");
    expect(searchPages(pages, "zzzz-no-such-word")).toEqual([]);
  });
});
