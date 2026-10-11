import { describe, expect, it } from "vitest";
import { ConflictError, Drafts } from "./drafts";

function memory() {
  const map = new Map<string, string>();
  return { getItem: (k: string) => map.get(k) ?? null, setItem: (k: string, v: string) => { map.set(k, v); },
           removeItem: (k: string) => { map.delete(k); }, map };
}

describe("drafts", () => {
  it("is clean when opened and dirty once the text differs", () => {
    const drafts = new Drafts();
    drafts.open(1, "a/B.java", "class B {}", "sha1");
    expect(drafts.isDirty(1)).toBe(false);
    drafts.setText(1, "class B { int x; }");
    expect(drafts.isDirty(1)).toBe(true);
    expect(drafts.dirtyIds()).toEqual([1]);
    drafts.setText(1, "class B {}");
    expect(drafts.isDirty(1)).toBe(false);
  });

  it("saves with the hash the file was opened with, and is clean after", async () => {
    const drafts = new Drafts();
    drafts.open(1, "a/B.java", "class B {}", "sha1");
    drafts.setText(1, "class B { int x; }");
    const calls: unknown[] = [];
    const result = await drafts.save(1, async (id, text, sha) => { calls.push([id, text, sha]); return { sha256: "sha2" }; }, (s) => s.sha256);
    expect(calls).toEqual([[1, "class B { int x; }", "sha1"]]);
    expect(result.saved).toEqual({ sha256: "sha2" });
    expect(drafts.isDirty(1)).toBe(false);
    expect(drafts.get(1)?.baseSha).toBe("sha2");
  });

  it("keeps what was typed during a save as unsaved", async () => {
    const drafts = new Drafts();
    drafts.open(1, "a/B.java", "", "sha1");
    drafts.setText(1, "one");
    await drafts.save(1, async () => { drafts.setText(1, "one two"); return { sha256: "sha2" }; }, (s) => s.sha256);
    expect(drafts.isDirty(1)).toBe(true);
    expect(drafts.get(1)).toMatchObject({ baseText: "one", text: "one two", baseSha: "sha2" });
  });

  it("records a conflict instead of overwriting, and lets either side win", async () => {
    const drafts = new Drafts();
    drafts.open(1, "a/B.java", "class B {}", "sha1");
    drafts.setText(1, "class B { int mine; }");
    const result = await drafts.save(1, async () => { throw new ConflictError("class B { int theirs; }", "sha9"); }, () => "");
    expect(result.conflict).toEqual({ fileId: 1, currentText: "class B { int theirs; }", currentSha: "sha9" });
    expect(drafts.conflict(1)).toBeDefined();
    expect(drafts.isDirty(1)).toBe(true);

    drafts.resolve(1, "mine");
    expect(drafts.conflict(1)).toBeUndefined();
    expect(drafts.get(1)).toMatchObject({ baseSha: "sha9", text: "class B { int mine; }" });
    expect(drafts.isDirty(1)).toBe(true);   // Saving now sends sha9 and overwrites

    drafts.open(2, "a/C.java", "x", "s1");
    drafts.setText(2, "y");
    await drafts.save(2, async () => { throw new ConflictError("z", "s2"); }, () => "");
    drafts.resolve(2, "theirs");
    expect(drafts.get(2)).toMatchObject({ baseSha: "s2", text: "z" });
    expect(drafts.isDirty(2)).toBe(false);
  });

  it("other errors are passed on and leave the draft as it was", async () => {
    const drafts = new Drafts();
    drafts.open(1, "a/B.java", "x", "sha1");
    drafts.setText(1, "y");
    await expect(drafts.save(1, async () => { throw new Error("The server stopped."); }, () => "")).rejects.toThrow("stopped");
    expect(drafts.isDirty(1)).toBe(true);
    expect(drafts.conflict(1)).toBeUndefined();
  });

  it("keeps unsaved text in storage and restores it for the same version of the file", () => {
    const storage = memory();
    const first = new Drafts(storage);
    first.open(1, "a/B.java", "x", "sha1");
    first.setText(1, "typed");
    first.open(2, "a/C.java", "clean", "sha2");
    expect(JSON.parse(storage.map.get("searchables-drafts")!)).toHaveLength(1);   // Clean drafts aren't kept

    const second = new Drafts(storage);
    expect(second.open(1, "a/B.java", "x", "sha1").text).toBe("typed");
    expect(second.isDirty(1)).toBe(true);
    second.setText(1, "x");
    expect(storage.map.has("searchables-drafts")).toBe(false);
  });

  it("opening a file changed on disk while a draft was unsaved becomes a conflict, not a loss", () => {
    const storage = memory();
    const first = new Drafts(storage);
    first.open(1, "a/B.java", "x", "sha1");
    first.setText(1, "typed");
    const second = new Drafts(storage);
    const draft = second.open(1, "a/B.java", "changed elsewhere", "sha2");
    expect(draft.text).toBe("typed");
    expect(second.conflict(1)).toEqual({ fileId: 1, currentText: "changed elsewhere", currentSha: "sha2" });
  });

  it("forgets a draft when discarded and follows a file that moved", () => {
    const drafts = new Drafts();
    drafts.open(1, "a/B.java", "x", "sha1");
    drafts.setText(1, "y");
    drafts.moved(1, "b/B.java");
    expect(drafts.get(1)?.path).toBe("b/B.java");
    drafts.discard(1);
    expect(drafts.get(1)).toBeUndefined();
    expect(drafts.dirtyIds()).toEqual([]);
  });

  it("tells listeners when anything changes", () => {
    const drafts = new Drafts();
    let calls = 0;
    const stop = drafts.subscribe(() => { calls++; });
    drafts.open(1, "a", "x", "s");
    drafts.setText(1, "y");
    drafts.setText(1, "y");   // No change: no call
    stop();
    drafts.setText(1, "z");
    expect(calls).toBe(2);
  });
});
