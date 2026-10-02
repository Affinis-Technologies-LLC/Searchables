// A source file's text, outline and imports, shared by the editor and the inspector.
import { api } from "../api";
import { useLoad } from "../hooks";
import { FileDetail } from "../types";

const cache = new Map<number, Promise<FileDetail>>();

export function loadFile(fileId: number): Promise<FileDetail> {
  if (!cache.has(fileId)) {
    if (cache.size > 80) cache.clear();
    const request = api.get<FileDetail>(`/code/files/${fileId}`);
    request.catch(() => cache.delete(fileId));
    cache.set(fileId, request);
  }
  return cache.get(fileId)!;
}

/** After a rescan, file ids and contents may have changed. */
export function forgetFiles(): void {
  cache.clear();
}

export function useFile(fileId: number) {
  return useLoad<FileDetail>(() => loadFile(fileId), [fileId]);
}
