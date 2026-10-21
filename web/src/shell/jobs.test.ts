import { describe, expect, it } from "vitest";
import { Job } from "../types";
import { indexingNotice, jobProgress, jobTitle } from "./jobs";

const job = (over: Partial<Job>): Job => ({
  id: 1, kind: "add", name: "Big standard.pdf", status: "running", stage: "Reading pages", done: 1200, total: 30000,
  result: "", warning: "", resumed: false, restarted: false, ...over,
});

describe("job labels (ADR-033)", () => {
  it("names the job, and says when it was resumed after a restart and whether it starts over", () => {
    expect(jobTitle(job({}))).toBe("Adding Big standard.pdf");
    expect(jobTitle(job({ kind: "embed", name: "Big standard" }))).toBe("Adding meaning search to Big standard");
    expect(jobTitle(job({ resumed: true }))).toBe("Resuming after a restart: adding Big standard.pdf");
    expect(jobTitle(job({ resumed: true, restarted: true }))).toBe("Resuming after a restart, from the first page: adding Big standard.pdf");
  });
  it("shows the stage with its count, or that the model is loading", () => {
    expect(jobProgress(job({}))).toBe("reading pages 1,200 of 30,000");
    expect(jobProgress(job({ stage: "Saving passages", done: 0, total: 360000 }))).toBe("saving passages 0 of 360,000");
    expect(jobProgress(job({ total: 0 }))).toBe("starting (loading the language model the first time)…");
  });
  it("tells the Search view what is running and that searches are slower meanwhile", () => {
    expect(indexingNotice([])).toBe("");
    expect(indexingNotice([job({})])).toBe("Adding Big standard.pdf (reading pages 1,200 of 30,000): searches answer more slowly until it's done.");
    expect(indexingNotice([job({ status: "queued" }), job({ kind: "code", name: "Shop", stage: "Linking references", done: 5, total: 9 })]))
      .toBe("Scanning Shop (linking references 5 of 9): searches answer more slowly until it's done.");
  });
});
