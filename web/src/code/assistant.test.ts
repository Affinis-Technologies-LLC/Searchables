import { describe, expect, it } from "vitest";
import { Assistant } from "./assistant";
import { ExamplesAnswer } from "../types";

function answer(digest: string, ids: number[]): ExamplesAnswer {
  return {
    context: { file_id: 1, language: "java", digest, expression: { kind: "call", name: "find", partial: "", receiver: "repository", args_so_far: 1, chain: "", start_col: 1 },
               enclosing: null, receiver_type: null, neighbours: { calls: [], types: [], shape: "" } },
    filter: "same member on the same type", by_name: false, weights: { T: 0.3, M: 0.25, C: 0.2, P: 0.15, Q: 0.1 },
    examples: ids.map((id) => ({ ref_id: id, file_id: 2, path: "A.java", line: id, col: 1, start: id, end: id, lines: ["x"], first_line: id,
                                  statement: "x", enclosing: `A#m${id}`, enclosing_id: id, target: "", certainty: "resolved",
                                  features: { T: 1, M: 1, C: 0, P: 0, Q: 1 }, score: 0.5, reason: "r" })),
  };
}

const later = <T,>(value: T, ms: number) => new Promise<T>((resolve) => setTimeout(() => resolve(value), ms));

describe("assistant", () => {
  it("keeps only the answer to the latest request", async () => {
    const a = new Assistant();
    const slow = a.request(1, "t", 1, 1, () => later(answer("old", [1]), 30));
    const fast = a.request(1, "t", 1, 2, () => later(answer("new", [2]), 5));
    await Promise.all([slow, fast]);
    expect(a.snapshot().status).toBe("ready");
    expect(a.snapshot().answer?.context.digest).toBe("new");
  });

  it("shows five at first, more on request, and forgets 'more' for a new context", async () => {
    const a = new Assistant();
    await a.request(1, "t", 1, 1, async () => answer("d1", [1, 2, 3, 4, 5, 6, 7]));
    expect(a.visible().map((e) => e.ref_id)).toEqual([1, 2, 3, 4, 5]);
    expect(a.hiddenCount()).toBe(2);
    a.showMore();
    expect(a.visible()).toHaveLength(7);
    await a.request(1, "t", 1, 1, async () => answer("d1", [1, 2, 3, 4, 5, 6, 7]));
    expect(a.visible()).toHaveLength(7);           // Same context: still showing all
    await a.request(1, "t", 2, 1, async () => answer("d2", [1, 2, 3, 4, 5, 6]));
    expect(a.visible()).toHaveLength(5);
  });

  it("hides dismissed examples for that context only", async () => {
    const a = new Assistant();
    await a.request(1, "t", 1, 1, async () => answer("d1", [1, 2, 3]));
    a.dismiss(2);
    expect(a.visible().map((e) => e.ref_id)).toEqual([1, 3]);
    await a.request(1, "t", 2, 1, async () => answer("d2", [1, 2, 3]));
    expect(a.visible().map((e) => e.ref_id)).toEqual([1, 2, 3]);
    await a.request(1, "t", 1, 1, async () => answer("d1", [1, 2, 3]));
    expect(a.visible().map((e) => e.ref_id)).toEqual([1, 3]);
  });

  it("reports an error and recovers on the next answer", async () => {
    const a = new Assistant();
    await a.request(1, "t", 1, 1, async () => { throw new Error("The server stopped."); });
    expect(a.snapshot().status).toBe("error");
    expect(a.snapshot().error).toContain("stopped");
    await a.request(1, "t", 1, 1, async () => answer("d", [1]));
    expect(a.snapshot().status).toBe("ready");
    a.clear();
    expect(a.snapshot().status).toBe("idle");
    expect(a.visible()).toEqual([]);
  });
});
