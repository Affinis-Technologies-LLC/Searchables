// The state behind the Examples view (ADR-012): the latest context the editor asked about, the
// examples the server found for it, which of them the developer dismissed, and how many are shown.
// Requests race: only the answer to the latest one is kept.
import { ExamplesAnswer } from "../types";

export const SHOWN_AT_FIRST = 5;

export interface AssistantState {
  status: "idle" | "loading" | "ready" | "error";
  fileId: number | null;
  answer: ExamplesAnswer | null;
  error: string;
  showAll: boolean;
}

export type Fetcher = (fileId: number, text: string, line: number, col: number) => Promise<ExamplesAnswer>;

export class Assistant {
  private state: AssistantState = { status: "idle", fileId: null, answer: null, error: "", showAll: false };
  private listeners = new Set<() => void>();
  private sequence = 0;
  private dismissed = new Map<string, Set<number>>();   // Context digest → example ref ids hidden for it

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  snapshot(): AssistantState {
    return this.state;
  }

  private set(patch: Partial<AssistantState>): void {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((listener) => listener());
  }

  /** Asks for the context at the cursor; an answer to an earlier request that arrives later is dropped. */
  async request(fileId: number, text: string, line: number, col: number, fetcher: Fetcher): Promise<void> {
    const id = ++this.sequence;
    this.set({ status: "loading", fileId });
    try {
      const answer = await fetcher(fileId, text, line, col);
      if (id !== this.sequence) return;
      const same = this.state.answer?.context.digest === answer.context.digest;
      this.set({ status: "ready", answer, error: "", showAll: same ? this.state.showAll : false });
    } catch (error) {
      if (id !== this.sequence) return;
      this.set({ status: "error", error: error instanceof Error ? error.message : String(error) });
    }
  }

  clear(): void {
    this.sequence++;
    this.set({ status: "idle", fileId: null, answer: null, error: "", showAll: false });
  }

  dismiss(refId: number): void {
    const digest = this.state.answer?.context.digest;
    if (!digest) return;
    if (!this.dismissed.has(digest)) this.dismissed.set(digest, new Set());
    this.dismissed.get(digest)!.add(refId);
    this.set({});
  }

  showMore(): void {
    this.set({ showAll: true });
  }

  /** The examples to show: not dismissed for this context, five at first. */
  visible(): ExamplesAnswer["examples"] {
    const answer = this.state.answer;
    if (!answer) return [];
    const hidden = this.dismissed.get(answer.context.digest) ?? new Set<number>();
    const kept = answer.examples.filter((e) => !hidden.has(e.ref_id));
    return this.state.showAll ? kept : kept.slice(0, SHOWN_AT_FIRST);
  }

  hiddenCount(): number {
    const answer = this.state.answer;
    if (!answer) return 0;
    const hidden = this.dismissed.get(answer.context.digest) ?? new Set<number>();
    return answer.examples.filter((e) => !hidden.has(e.ref_id)).length - this.visible().length;
  }
}

export const assistant = new Assistant();
