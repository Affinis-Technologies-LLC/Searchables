import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import "pdfjs-dist/web/pdf_viewer.css";
import { CSSProperties, MouseEvent, useEffect, useMemo, useRef, useState } from "react";
import { DocTab, useApp } from "../store";
import { BBox, Block } from "../types";
import { Segments, Status } from "../ui";
import { usePage } from "./pages";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

// One loaded PDF per document, kept while the app is open (pages are fetched from the server as they're needed)
const documents = new Map<number, Promise<pdfjs.PDFDocumentProxy>>();

function loadDocument(docId: number): Promise<pdfjs.PDFDocumentProxy> {
  if (!documents.has(docId)) {
    const task = pdfjs.getDocument({
      url: `/api/documents/${docId}/file`, withCredentials: true,
      cMapUrl: "/pdfjs/cmaps/", cMapPacked: true, standardFontDataUrl: "/pdfjs/standard_fonts/",
    });
    task.promise.catch(() => documents.delete(docId));
    documents.set(docId, task.promise);
  }
  return documents.get(docId)!;
}

const ZOOMS = ["Fit", "125%", "150%", "200%"] as const;
const FACTOR = { Fit: 1, "125%": 1.25, "150%": 1.5, "200%": 2 };
const PADDING = 4;   // PDF points between a passage and its outline

function area(box: BBox): number {
  return (box[2] - box[0]) * (box[3] - box[1]);
}

/** The real page, with search hits highlighted; its text can be selected, and its passages clicked to explore them. */
export function PdfView({ tab, visible }: { tab: DocTab; visible: boolean }) {
  const app = useApp();
  const doc = app.overview.documents.find((d) => d.id === tab.docId);
  const { data, loading, error } = usePage(tab.docId, tab.page, tab.highlight);
  const [pdf, setPdf] = useState<pdfjs.PDFDocumentProxy | null>(null);
  const [failed, setFailed] = useState("");
  const [zoom, setZoom] = useState<(typeof ZOOMS)[number]>("Fit");
  const [width, setWidth] = useState(0);
  const [size, setSize] = useState<{ width: number; height: number; scale: number } | null>(null);
  const [hover, setHover] = useState<Block | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const textLayer = useRef<HTMLDivElement>(null);

  useEffect(() => {
    loadDocument(tab.docId).then(setPdf, (e) => setFailed(e?.message ?? String(e)));
  }, [tab.docId]);

  useEffect(() => {
    const element = scroller.current;
    if (!element) return;
    const observer = new ResizeObserver(() => setWidth(element.clientWidth));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // Draw the page and lay its (invisible, selectable) text over it
  useEffect(() => {
    if (!pdf || !width || !visible) return;
    let cancelled = false;
    let task: pdfjs.RenderTask | null = null;
    (async () => {
      const page = await pdf.getPage(Math.min(tab.page, pdf.numPages));
      const natural = page.getViewport({ scale: 1 });
      const scale = ((width - 32) / natural.width) * FACTOR[zoom];
      const viewport = page.getViewport({ scale });
      const ratio = window.devicePixelRatio || 1;
      const element = canvas.current;
      if (cancelled || !element) return;
      element.width = Math.floor(viewport.width * ratio);
      element.height = Math.floor(viewport.height * ratio);
      setSize({ width: viewport.width, height: viewport.height, scale });
      task = page.render({ canvasContext: element.getContext("2d")!, viewport,
                           transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : undefined });
      await task.promise;
      const layer = textLayer.current;
      if (cancelled || !layer) return;
      layer.replaceChildren();
      layer.style.setProperty("--scale-factor", String(scale));
      await new pdfjs.TextLayer({ textContentSource: page.streamTextContent(), container: layer, viewport }).render();
    })().catch((e) => { if (e?.name !== "RenderingCancelledException" && !cancelled) setFailed(e?.message ?? String(e)); });
    return () => { cancelled = true; task?.cancel(); };
  }, [pdf, tab.page, width, zoom, visible]);

  const selected = useMemo(() => data?.blocks.find((b) => b.id === tab.blockId) ?? null, [data, tab.blockId]);
  const outline = tab.target ?? selected?.bbox ?? null;

  // Bring what was navigated to into view
  useEffect(() => {
    if (!size || !scroller.current) return;
    scroller.current.scrollTo({ top: outline ? Math.max(outline[1] * size.scale - 120, 0) : 0 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab.nonce, size?.scale]);

  const go = (page: number) => {
    if (!doc || page < 1 || page > doc.page_count || page === tab.page) return;
    app.updateDoc(tab.id, { page, target: null, blockId: null, nonce: tab.nonce + 0.001 });
  };

  const blockAt = (event: MouseEvent): Block | null => {
    if (!size || !data) return null;
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = (event.clientX - bounds.left) / size.scale, y = (event.clientY - bounds.top) / size.scale;
    const under = data.blocks.filter((b) => b.bbox && x >= b.bbox[0] && x <= b.bbox[2] && y >= b.bbox[1] && y <= b.bbox[3]);
    return under.sort((a, b) => area(a.bbox!) - area(b.bbox!))[0] ?? null;   // The innermost passage
  };

  const box = (bbox: BBox, pad = 0): CSSProperties => size ? {
    left: (bbox[0] - pad) * size.scale, top: (bbox[1] - pad) * size.scale,
    width: (bbox[2] - bbox[0] + 2 * pad) * size.scale, height: (bbox[3] - bbox[1] + 2 * pad) * size.scale,
  } : {};

  const earlier = data?.hit_pages.filter((p) => p < tab.page) ?? [];
  const later = data?.hit_pages.filter((p) => p > tab.page) ?? [];

  if (!doc) return <div className="notice">This document is no longer in the library.</div>;
  return (
    <div className="viewer" tabIndex={0}
         onKeyDown={(e) => {
           if (e.altKey || e.ctrlKey || e.metaKey || (e.target as HTMLElement).tagName === "INPUT") return;
           if (e.key === "ArrowRight" || e.key === "PageDown") { e.preventDefault(); go(tab.page + 1); }
           if (e.key === "ArrowLeft" || e.key === "PageUp") { e.preventDefault(); go(tab.page - 1); }
         }}>
      <div className="toolbar">
        <button type="button" disabled={tab.page <= 1} onClick={() => go(tab.page - 1)} title="Previous page (←)">◀</button>
        <input type="number" className="page-input" min={1} max={doc.page_count} value={tab.page} aria-label="Page"
               onChange={(e) => go(Number(e.target.value))} />
        <span className="muted">of {doc.page_count}{data && data.page_label !== String(tab.page) ? ` · printed ${data.page_label}` : ""}</span>
        <button type="button" disabled={tab.page >= doc.page_count} onClick={() => go(tab.page + 1)} title="Next page (→)">▶</button>
        {data && data.hit_pages.length > 0 && (
          <>
            <span className="sep" />
            <button type="button" disabled={!earlier.length} onClick={() => go(earlier[earlier.length - 1])}
                    title="Previous page in this document with a match">◀ Hit</button>
            <button type="button" disabled={!later.length} onClick={() => go(later[0])}
                    title="Next page in this document with a match">Hit ▶</button>
            <span className="muted">{data.hits.length} on this page · {data.hit_pages.length} page{data.hit_pages.length === 1 ? "" : "s"}</span>
          </>
        )}
        <span className="grow" />
        {doc.distribution && <span className="badge badge-marking" title={doc.distribution}>{doc.distribution.split(".")[0]}</span>}
        <Segments options={ZOOMS} value={zoom} onChange={setZoom} />
      </div>
      <Status loading={loading && !data} error={failed || error} />
      <div className="page-scroll" ref={scroller}>
        <div className="page" style={size ? { width: size.width, height: size.height } : undefined}
             onMouseMove={(e) => setHover(blockAt(e))} onMouseLeave={() => setHover(null)}
             onMouseUp={(e) => {
               // A click explores the passage under it; dragging selects text instead
               const block = blockAt(e);
               if (block && !window.getSelection()?.toString()) app.updateDoc(tab.id, { blockId: block.id, target: null });
             }}>
          <canvas ref={canvas} style={size ? { width: size.width, height: size.height } : undefined} />
          <div className="overlay">
            {data?.hits.map((hit, i) => <div key={i} className="hit" style={box(hit)} />)}
            {hover?.bbox && hover.id !== selected?.id && <div className="passage hover" style={box(hover.bbox, PADDING)} />}
            {outline && <div className="passage selected" style={box(outline, PADDING)} />}
          </div>
          <div className="textLayer" ref={textLayer} />
        </div>
      </div>
    </div>
  );
}
