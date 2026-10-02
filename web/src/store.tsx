// What the whole app shares: the library overview, the open tabs, where you've been, and the active collection.
import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { At, BBox, Block, Overview } from "./types";

export type Activity = "search" | "contents" | "catalogue" | "glossary" | "compare" | "collections" | "library" | "code";

/** What a document tab highlights: the words of a search, or an identifier. */
export interface Highlight { q?: string; identifier?: string; children?: boolean }

export interface DocTab {
  id: string;
  kind: "doc";
  docId: number;
  page: number;
  target: BBox | null;      // A region to outline (a followed reference, an opened pin)
  blockId: number | null;   // The passage being explored
  highlight: Highlight;
  nonce: number;            // Changes on every navigation, so the view scrolls even to the same place
}

export interface CodeTab { id: string; kind: "code"; fileId: number; path: string; line: number; nonce: number }

export type Tab = DocTab | CodeTab;

export interface DocLocation { docId: number; page: number; target?: BBox | null; blockId?: number | null; highlight?: Highlight }
export interface CodeLocation { fileId: number; path: string; line: number }

interface Toast { id: number; text: string; kind: "info" | "error" }

interface AppContext {
  overview: Overview;
  refresh: () => Promise<void>;
  activity: Activity;
  setActivity: (activity: Activity) => void;
  tabs: Tab[];
  active: Tab | null;
  activate: (id: string) => void;
  close: (id: string) => void;
  openDoc: (location: DocLocation) => void;
  openCode: (location: CodeLocation) => void;
  updateDoc: (id: string, patch: Partial<DocTab>) => void;
  back: () => void;
  forward: () => void;
  canGoBack: boolean;
  canGoForward: boolean;
  collectionId: number;
  setCollectionId: (id: number) => void;
  pinned: Set<string>;
  pinsVersion: number;
  togglePin: (block: Block, query?: string) => Promise<void>;
  pinSymbol: (symbolId: number) => Promise<void>;
  pinsChanged: () => void;
  symbolId: number | null;      // The code symbol the inspector shows
  setSymbolId: (id: number | null) => void;
  at: At | null;                // What's under the cursor in the code view, when it isn't a symbol of the codebase
  setAt: (at: At | null) => void;
  toasts: Toast[];
  notify: (text: string, kind?: "info" | "error") => void;
  run: <T,>(action: Promise<T>) => Promise<T | undefined>;
}

const Context = createContext<AppContext | null>(null);

export function useApp(): AppContext {
  const context = useContext(Context);
  if (!context) throw new Error("useApp outside the app");
  return context;
}

type Place = { tab: Tab };

export function AppProvider({ initial, children }: { initial: Overview; children: ReactNode }) {
  const [overview, setOverview] = useState(initial);
  const [activity, setActivity] = useState<Activity>("search");
  const [tabs, setTabs] = useState<Tab[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [collectionId, setCollectionId] = useState(initial.collections[0]?.id ?? 0);
  const [pinned, setPinned] = useState<Set<string>>(new Set());
  const [pinsVersion, setPinsVersion] = useState(0);
  const [symbolId, setSymbolId] = useState<number | null>(null);
  const [at, setAt] = useState<At | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const history = useRef<{ places: Place[]; index: number }>({ places: [], index: -1 });
  const [, setHistoryTick] = useState(0);
  const nonce = useRef(1);

  const notify = useCallback((text: string, kind: "info" | "error" = "info") => {
    const id = Date.now() + Math.random();
    setToasts((all) => [...all, { id, text, kind }]);
    setTimeout(() => setToasts((all) => all.filter((t) => t.id !== id)), kind === "error" ? 8000 : 4000);
  }, []);

  /** Runs a server call, showing its error as a notice instead of failing silently. */
  const run = useCallback(async <T,>(action: Promise<T>): Promise<T | undefined> => {
    try {
      return await action;
    } catch (error) {
      notify(error instanceof Error ? error.message : String(error), "error");
      return undefined;
    }
  }, [notify]);

  const refresh = useCallback(async () => {
    try {
      setOverview(await api.get<Overview>("/state"));
    } catch { /* Signed out or the server stopped: the app shows that elsewhere */ }
  }, []);

  // Indexing progress is polled while anything is running, and now and then otherwise
  const busy = overview.jobs.active.length > 0;
  useEffect(() => {
    const timer = setInterval(refresh, busy ? 1500 : 15000);
    return () => clearInterval(timer);
  }, [busy, refresh]);

  useEffect(() => {
    if (!overview.collections.some((c) => c.id === collectionId) && overview.collections.length) {
      setCollectionId(overview.collections[0].id);
    }
  }, [overview.collections, collectionId]);

  useEffect(() => {
    if (!collectionId) return;
    api.get<{ keys: string[] }>(`/collections/${collectionId}/pins`).then((r) => setPinned(new Set(r.keys))).catch(() => {});
  }, [collectionId, pinsVersion]);

  const show = useCallback((tab: Tab, record: boolean) => {
    setTabs((all) => (all.some((t) => t.id === tab.id) ? all.map((t) => (t.id === tab.id ? tab : t)) : [...all, tab]));
    setActiveId(tab.id);
    if (record) {
      const h = history.current;
      h.places = [...h.places.slice(0, h.index + 1), { tab }].slice(-100);
      h.index = h.places.length - 1;
      setHistoryTick((n) => n + 1);
    }
  }, []);

  const openDoc = useCallback((location: DocLocation) => {
    show({
      id: `doc:${location.docId}`, kind: "doc", docId: location.docId, page: location.page,
      target: location.target ?? null, blockId: location.blockId ?? null,
      highlight: location.highlight ?? {}, nonce: nonce.current++,
    }, true);
  }, [show]);

  const openCode = useCallback((location: CodeLocation) => {
    show({ id: `code:${location.fileId}`, kind: "code", fileId: location.fileId, path: location.path,
           line: location.line, nonce: nonce.current++ }, true);
  }, [show]);

  const updateDoc = useCallback((id: string, patch: Partial<DocTab>) => {
    setTabs((all) => all.map((t) => (t.id === id && t.kind === "doc" ? { ...t, ...patch } : t)));
  }, []);

  const step = useCallback((delta: number) => {
    const h = history.current;
    const next = h.index + delta;
    if (next < 0 || next >= h.places.length) return;
    h.index = next;
    show({ ...h.places[next].tab, nonce: nonce.current++ }, false);
    setHistoryTick((n) => n + 1);
  }, [show]);

  // The document in view is kept in the address (#doc=3&page=12&q=…), so it can be bookmarked and survives a reload
  const current = tabs.find((t) => t.id === activeId);
  useEffect(() => {
    if (current?.kind !== "doc") return;
    const params = new URLSearchParams({ doc: String(current.docId), page: String(current.page) });
    if (current.highlight.identifier) params.set("id", current.highlight.identifier);
    else if (current.highlight.q) params.set("q", current.highlight.q);
    window.history.replaceState(null, "", "#" + params.toString());
  }, [current]);
  useEffect(() => {
    const params = new URLSearchParams(window.location.hash.slice(1));
    const docId = Number(params.get("doc")), page = Number(params.get("page") ?? 1);
    if (initial.documents.some((d) => d.id === docId)) {
      openDoc({ docId, page: Math.max(page, 1), highlight: params.get("id") ? { identifier: params.get("id")! } : params.get("q") ? { q: params.get("q")! } : {} });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const close = useCallback((id: string) => {
    setTabs((all) => {
      const remaining = all.filter((t) => t.id !== id);
      setActiveId((current) => (current === id ? remaining[remaining.length - 1]?.id ?? null : current));
      return remaining;
    });
  }, []);

  const togglePin = useCallback(async (block: Block, queryText = "") => {
    if (block.pin_key && pinned.has(block.pin_key)) {
      await run(api.del(`/collections/${collectionId}/pins?key=${block.pin_key}`));
    } else {
      await run(api.post(`/collections/${collectionId}/pins`, { block_id: block.id, query: queryText }));
    }
    setPinsVersion((n) => n + 1);
    refresh();
  }, [collectionId, pinned, refresh, run]);

  const pinSymbol = useCallback(async (id: number) => {
    if (await run(api.post(`/collections/${collectionId}/pins`, { symbol_id: id }))) notify("Pinned to the collection");
    setPinsVersion((n) => n + 1);
    refresh();
  }, [collectionId, notify, refresh, run]);

  const value = useMemo<AppContext>(() => ({
    overview, refresh, activity, setActivity, tabs,
    active: tabs.find((t) => t.id === activeId) ?? null,
    activate: setActiveId, close, openDoc, openCode, updateDoc,
    back: () => step(-1), forward: () => step(1),
    canGoBack: history.current.index > 0,
    canGoForward: history.current.index < history.current.places.length - 1,
    collectionId, setCollectionId, pinned, pinsVersion, togglePin, pinSymbol,
    pinsChanged: () => { setPinsVersion((n) => n + 1); refresh(); },
    symbolId, setSymbolId, at, setAt, toasts, notify, run,
  }), [at, overview, refresh, activity, tabs, activeId, close, openDoc, openCode, updateDoc, step, collectionId, pinned,
       pinsVersion, togglePin, pinSymbol, symbolId, toasts, notify, run]);

  return <Context.Provider value={value}>{children}</Context.Provider>;
}
