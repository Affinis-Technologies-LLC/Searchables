// Saving, creating, renaming and deleting source files through the server (ADR-011). Every change
// carries the hash the file was opened with; a 409 means it changed on disk and becomes a conflict.
import { api, ApiError } from "../api";
import { FileDetail, SavedFile } from "../types";
import { ConflictError, drafts } from "./drafts";
import { forgetFile, loadFile, rememberFile } from "./files";

async function saver(fileId: number, text: string, sha256: string): Promise<SavedFile> {
  try {
    return await api.put<SavedFile>(`/code/files/${fileId}`, { text, sha256 });
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      throw new ConflictError(String(error.body.current_text ?? ""), String(error.body.current_sha256 ?? ""));
    }
    throw error;
  }
}

/** Saves a file's draft. Returns the saved file, or nothing when there was no change or a conflict (kept in `drafts`). */
export async function saveFile(fileId: number): Promise<SavedFile | undefined> {
  const text = drafts.text(fileId);
  if (text === undefined) return undefined;
  const result = await drafts.save(fileId, saver, (saved) => saved.file.sha256);
  if (result.saved) {
    const detail: FileDetail = { ...result.saved, text, editable: true };
    rememberFile(detail);
  }
  return result.saved;
}

export async function createFile(codebaseId: number, path: string, text = ""): Promise<SavedFile> {
  const saved = await api.post<SavedFile>(`/codebases/${codebaseId}/files`, { path, text });
  rememberFile({ ...saved, text, editable: true });
  return saved;
}

export async function renameFile(fileId: number, path: string): Promise<SavedFile> {
  const current = await loadFile(fileId);
  const saved = await api.post<SavedFile>(`/code/files/${fileId}/rename`, { path, sha256: current.file.sha256 });
  rememberFile({ ...saved, text: current.text, editable: true });
  drafts.moved(fileId, saved.file.path, saved.file.sha256);
  return saved;
}

export async function deleteFile(fileId: number): Promise<void> {
  const current = await loadFile(fileId);
  await api.del(`/code/files/${fileId}`, { sha256: current.file.sha256 });
  forgetFile(fileId);
  drafts.discard(fileId);
}
