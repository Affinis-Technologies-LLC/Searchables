// A document page's data (passages, hits, tables, references), shared by the page view and the inspector.
import { api, query } from "../api";
import { useLoad } from "../hooks";
import { Highlight, useApp } from "../store";
import { PageData } from "../types";

const cache = new Map<string, Promise<PageData>>();

export function usePage(docId: number, page: number, highlight: Highlight) {
  const { overview } = useApp();
  // Re-indexing a document renumbers its passages: its passage count is part of the key so stale pages aren't reused
  const stamp = overview.documents.find((d) => d.id === docId)?.block_count ?? 0;
  const url = `/documents/${docId}/pages/${page}` + query({ q: highlight.identifier ? undefined : highlight.q,
    identifier: highlight.identifier, children: highlight.children });
  return useLoad<PageData>(() => {
    const key = `${stamp}:${url}`;
    if (!cache.has(key)) {
      if (cache.size > 60) cache.clear();
      const request = api.get<PageData>(url);
      request.catch(() => cache.delete(key));
      cache.set(key, request);
    }
    return cache.get(key)!;
  }, [url, stamp]);
}
