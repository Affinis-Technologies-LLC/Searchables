// What the status bar, the Library's Jobs list and the Search view say about indexing (ADR-033).
import { Job } from "../types";

const JOB_LABEL: Record<Job["kind"], string> = { add: "Adding", reindex: "Re-indexing", embed: "Adding meaning search to", code: "Scanning" };

/** "Adding X"; or that it was resumed after a restart and, for an add stopped during reading, that it starts over. */
export function jobTitle(job: Job): string {
  if (!job.resumed) return `${JOB_LABEL[job.kind]} ${job.name}`;
  const doing = `${JOB_LABEL[job.kind].toLowerCase()} ${job.name}`;
  return job.restarted ? `Resuming after a restart, from the first page: ${doing}` : `Resuming after a restart: ${doing}`;
}

/** The stage with its count ("reading pages 1,200 of 30,000"), or that the model is still loading. */
export function jobProgress(job: Job): string {
  return job.total
    ? `${job.stage.toLowerCase()} ${job.done.toLocaleString()} of ${job.total.toLocaleString()}`
    : "starting (loading the language model the first time)…";
}

/** One line for the Search view while a job runs: what, how far, and that searches are slower meanwhile. */
export function indexingNotice(active: Job[]): string {
  const running = active.find((j) => j.status === "running");
  return running ? `${jobTitle(running)} (${jobProgress(running)}): searches answer more slowly until it's done.` : "";
}
