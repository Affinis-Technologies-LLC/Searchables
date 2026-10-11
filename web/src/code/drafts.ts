// Unsaved changes to source files (ADR-011): kept here, outside the editor, so they survive switching
// tabs and views, and in the browser's storage so a reload doesn't lose them. Saving sends the hash the
// file was opened with; the server refuses to overwrite a file changed on disk, and the conflict is
// kept here too, for the editor to show.

export interface Draft {
  fileId: number;
  path: string;
  baseSha: string;    // The file on disk as the editor opened it (or last saved it)
  baseText: string;
  text: string;       // What's in the editor now
}

export interface Conflict { fileId: number; currentText: string; currentSha: string }

export interface SaveResult<T> { saved?: T; conflict?: Conflict }

export interface Saver<T> {
  (fileId: number, text: string, sha256: string): Promise<T>;
}

/** Thrown (or returned) by a saver when the server answered 409: the file changed on disk. */
export class ConflictError extends Error {
  constructor(public currentText: string, public currentSha: string) {
    super("The file has changed on disk since it was opened.");
  }
}

interface Storage { getItem(key: string): string | null; setItem(key: string, value: string): void; removeItem(key: string): void }

const KEY = "searchables-drafts";

export class Drafts {
  private drafts = new Map<number, Draft>();
  private conflicts = new Map<number, Conflict>();
  private listeners = new Set<() => void>();

  constructor(private storage: Storage | null = null) {
    this.restore();
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  private changed(): void {
    this.persist();
    this.listeners.forEach((listener) => listener());
  }

  /** The editor opened a file: its text as it is on disk. A draft kept for the same version stays. */
  open(fileId: number, path: string, text: string, sha256: string): Draft {
    const kept = this.drafts.get(fileId);
    if (kept && kept.baseSha === sha256) {
      if (kept.path !== path) this.drafts.set(fileId, { ...kept, path });
      return this.drafts.get(fileId)!;
    }
    const draft = { fileId, path, baseSha: sha256, baseText: text, text };
    this.drafts.set(fileId, draft);
    if (kept && kept.text !== kept.baseText) {
      // The file was changed on disk (a rescan, another editor) while an unsaved draft existed: keep the draft as a conflict
      this.conflicts.set(fileId, { fileId, currentText: text, currentSha: sha256 });
      this.drafts.set(fileId, { ...draft, text: kept.text });
    }
    this.changed();
    return this.drafts.get(fileId)!;
  }

  get(fileId: number): Draft | undefined {
    return this.drafts.get(fileId);
  }

  text(fileId: number): string | undefined {
    return this.drafts.get(fileId)?.text;
  }

  setText(fileId: number, text: string): void {
    const draft = this.drafts.get(fileId);
    if (!draft || draft.text === text) return;
    this.drafts.set(fileId, { ...draft, text });
    this.changed();
  }

  isDirty(fileId: number): boolean {
    const draft = this.drafts.get(fileId);
    return !!draft && draft.text !== draft.baseText;
  }

  dirtyIds(): number[] {
    return [...this.drafts.values()].filter((d) => d.text !== d.baseText).map((d) => d.fileId);
  }

  conflict(fileId: number): Conflict | undefined {
    return this.conflicts.get(fileId);
  }

  /** Forgets a file's draft (its tab was closed and the changes discarded, or the file was deleted). */
  discard(fileId: number): void {
    this.drafts.delete(fileId);
    this.conflicts.delete(fileId);
    this.changed();
  }

  /** Where a file moved to. */
  moved(fileId: number, path: string, sha256?: string): void {
    const draft = this.drafts.get(fileId);
    if (draft) this.drafts.set(fileId, { ...draft, path, baseSha: sha256 ?? draft.baseSha });
    this.changed();
  }

  /** Saves the draft with the given saver; on a conflict nothing is written and the editor is told. */
  async save<T>(fileId: number, saver: Saver<T>, settle: (saved: T) => string): Promise<SaveResult<T>> {
    const draft = this.drafts.get(fileId);
    if (!draft) return {};
    const text = draft.text;
    try {
      const saved = await saver(fileId, text, draft.baseSha);
      const sha = settle(saved);
      const current = this.drafts.get(fileId) ?? draft;
      this.drafts.set(fileId, { ...current, baseSha: sha, baseText: text });   // Typing during the save stays unsaved
      this.conflicts.delete(fileId);
      this.changed();
      return { saved };
    } catch (error) {
      if (error instanceof ConflictError) {
        const conflict = { fileId, currentText: error.currentText, currentSha: error.currentSha };
        this.conflicts.set(fileId, conflict);
        this.changed();
        return { conflict };
      }
      throw error;
    }
  }

  /** The developer chose: keep what they typed over the version on disk, or take the version on disk. */
  resolve(fileId: number, choice: "mine" | "theirs"): Draft | undefined {
    const draft = this.drafts.get(fileId), conflict = this.conflicts.get(fileId);
    if (!draft || !conflict) return draft;
    const resolved = choice === "mine"
      ? { ...draft, baseSha: conflict.currentSha, baseText: conflict.currentText }         // Still dirty: saving now overwrites
      : { ...draft, baseSha: conflict.currentSha, baseText: conflict.currentText, text: conflict.currentText };
    this.drafts.set(fileId, resolved);
    this.conflicts.delete(fileId);
    this.changed();
    return resolved;
  }

  // ---- Browser storage: unsaved text only; clean drafts aren't worth keeping ----

  private persist(): void {
    if (!this.storage) return;
    try {
      const dirty = [...this.drafts.values()].filter((d) => d.text !== d.baseText);
      if (dirty.length) this.storage.setItem(KEY, JSON.stringify(dirty));
      else this.storage.removeItem(KEY);
    } catch { /* Storage full or unavailable: the draft lives on in memory */ }
  }

  private restore(): void {
    if (!this.storage) return;
    try {
      const kept = JSON.parse(this.storage.getItem(KEY) ?? "[]") as Draft[];
      for (const draft of kept) {
        if (typeof draft.fileId === "number" && typeof draft.text === "string") this.drafts.set(draft.fileId, draft);
      }
    } catch { /* Not ours, or broken: start clean */ }
  }
}

export const drafts = new Drafts(typeof window !== "undefined" ? window.localStorage : null);
