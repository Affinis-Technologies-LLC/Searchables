// The Links view (ADR-031): drop a PDF, read what's wrong with its internal links and bookmarks,
// untick what shouldn't change, download it fixed. The file is held by the server for the session
// and never enters the library.
import { useRef, useState } from "react";
import { api } from "../api";
import { useLoad } from "../hooks";
import { LinksTab, useApp } from "../store";
import { BookmarkState, LinkReport, LinkState, ReportLink } from "../types";
import { Badge, Empty, Icon, saveText, Status, tableToCsv } from "../ui";

const STATE_ORDER: LinkState[] = ["dead", "wrong page", "unresolved", "ok", "external"];
const STATE_TEXT: Record<LinkState, string> = {
  "dead": "Dead: the destination no longer exists",
  "wrong page": "Wrong page: the text under the link is somewhere else",
  "unresolved": "Unresolved: dead, and the text under the link is not a reference the document can place",
  "ok": "OK",
  "external": "External: not checked (the app is offline)",
};
const STATE_BADGE: Record<BookmarkState, string> = { "dead": "requirement", "wrong page": "page", "unresolved": "", "ok": "object", "external": "", "unchecked": "" };

export function LinksPanel() {
  const app = useApp();
  const picker = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [checking, setChecking] = useState("");
  const [report, setReport] = useState<LinkReport | null>(null);
  const [skipped, setSkipped] = useState<Set<number>>(new Set());
  const [addLinks, setAddLinks] = useState(false);
  const [rebuild, setRebuild] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);

  const checkFile = async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".pdf")) { app.notify(`${file.name} isn't a PDF.`, "error"); return; }
    setChecking(file.name);
    setReport(null); setSkipped(new Set()); setSelected(null); setRebuild(false); setAddLinks(false);
    const result = await app.run(api.upload<LinkReport>(`/links/check?filename=${encodeURIComponent(file.name)}`, file));
    setChecking("");
    if (result) {
      setReport(result);
      const first = result.links.find((l) => l.proposed_page !== null) ?? result.links[0];
      if (first) show(result, first);
    }
  };
  const show = (r: LinkReport, link: ReportLink) => {
    setSelected(link.id);
    app.openLinks({ token: r.token, filename: r.filename, page: link.page, pageCount: r.page_count, rect: link.rect });
  };
  const showTarget = (r: LinkReport, link: ReportLink) => {
    if (link.proposed_page === null) return;
    setSelected(link.id);
    app.openLinks({ token: r.token, filename: r.filename, page: link.proposed_page, pageCount: r.page_count, rect: null });
  };
  const toggle = (id: number) => setSkipped((s) => { const next = new Set(s); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  const drop = (event: React.DragEvent) => {
    event.preventDefault(); setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file) checkFile(file);
  };

  const fixable = report ? report.links.filter((l) => l.proposed_page !== null) : [];
  const applying = fixable.filter((l) => !skipped.has(l.id)).length;
  const bookmarkFixes = report ? report.bookmarks.filter((b) => b.proposed_page !== null).length : 0;
  const retitled = report ? report.bookmarks.filter((b) => b.proposed_title !== null).length : 0;
  const headings = report ? report.bookmarks.filter((b) => b.state !== "unresolved" && b.state !== "unchecked").length + report.unbookmarked.length : 0;
  const downloadHref = report
    ? `/api/links/${report.token}/fixed?skip=${encodeURIComponent([...skipped].join(","))}${addLinks ? "&add=1" : ""}${rebuild ? "&outline=1" : ""}`
    : "";
  const csv = () => report && saveText(`${report.filename} links.csv`, tableToCsv({
    columns: ["Page", "Text", "Kind", "Points to", "State", "Reference", "Proposed page"],
    rows: report.links.map((l) => [String(l.page), l.text, l.kind, l.target, l.state, l.reference, l.proposed_page === null ? "" : String(l.proposed_page)]),
  }));

  return (
    <div className="panel">
      <div className="panel-head">
        <div className={`dropzone ${dragging ? "over" : ""}`} onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
             onDragLeave={() => setDragging(false)} onDrop={drop} onClick={() => picker.current?.click()} role="button" tabIndex={0}>
          <Icon name="plus" /> Check a PDF's links: drop it here, or click to choose
          <input ref={picker} type="file" accept="application/pdf,.pdf" hidden
                 onChange={(e) => { if (e.target.files?.[0]) checkFile(e.target.files[0]); e.target.value = ""; }} />
        </div>
      </div>
      <div className="panel-body">
        {checking && <div className="loading">Checking {checking}… (the document is read whole; a long standard takes a few seconds)</div>}
        {!checking && !report && (
          <Empty>
            Internal links and bookmarks are checked against where the document itself puts each clause, table, figure and annex.
            A dead or mis-pointed link whose text names one of them is re-pointed there; the rest are listed for you. The PDF
            is not added to the library, and nothing is sent anywhere.
          </Empty>
        )}
        {report && report.refused && <div className="notice error">{report.refused}</div>}
        {report && !report.refused && (
          <>
            <div className="group-title">{report.filename} · {report.page_count} pages · {report.links.length} links, {report.bookmarks.length} bookmarks</div>
            <div className="row wrap">
              {STATE_ORDER.map((state) => <Badge key={state} kind={STATE_BADGE[state]} title={STATE_TEXT[state]}>{report.counts[state] ?? 0} {state}</Badge>)}
            </div>
            <div className="notice ok">
              <div className="grow">
                <b>{applying} of {fixable.length}</b> link fix{fixable.length === 1 ? "" : "es"} and <b>{bookmarkFixes}</b> bookmark fix{bookmarkFixes === 1 ? "" : "es"}{retitled > 0 ? ` (${retitled} retitled)` : ""} will be applied.
                {(report.unbookmarked.length > 0 || report.bookmarks.length === 0) && headings > 0 && (
                  <label className="row"><input type="checkbox" checked={rebuild} onChange={(e) => setRebuild(e.target.checked)} />
                    Rebuild the bookmarks from the {headings} headings{report.bookmarks.length > 0 ? ` (replaces the ${report.bookmarks.length} existing)` : ""}</label>
                )}
                {report.unlinked.length > 0 && (
                  <label className="row"><input type="checkbox" checked={addLinks} onChange={(e) => setAddLinks(e.target.checked)} />
                    Also add links for the {report.unlinked.length} reference{report.unlinked.length === 1 ? "" : "s"} that have none</label>
                )}
              </div>
              <a className="link" href={downloadHref} download>Download fixed PDF</a>
              <button type="button" className="link" onClick={csv}><Icon name="download" size={13} /> CSV</button>
            </div>
            {STATE_ORDER.filter((state) => report.links.some((l) => l.state === state)).map((state) => (
              <div key={state}>
                <div className="group-title" title={STATE_TEXT[state]}>{state} · {report.counts[state]}</div>
                {report.links.filter((l) => l.state === state).map((link) => (
                  <div key={link.id} className={`row line ${selected === link.id ? "selected" : ""}`}>
                    {link.proposed_page !== null
                      ? <input type="checkbox" checked={!skipped.has(link.id)} onChange={() => toggle(link.id)} title="Apply this fix" aria-label={`Fix link ${link.id}`} />
                      : <span style={{ width: 13 }} />}
                    <span className="grow">
                      <b>{link.text || "(no text)"}</b> <small className="muted">· p. {link.page} · {link.kind === "uri" ? link.target : `points to ${link.target}`}</small>
                      {link.proposed_page !== null && <><br /><small>{link.reference} is on page {link.proposed_page}: re-point there</small></>}
                      {link.state === "unresolved" && <><br /><small className="muted">Dead, and "{link.text}" is not a reference the document can place.</small></>}
                    </span>
                    <button type="button" onClick={() => show(report, link)} title="Show the link on its page">Show</button>
                    {link.proposed_page !== null && <button type="button" onClick={() => showTarget(report, link)} title="Show where it would point">Target</button>}
                  </div>
                ))}
              </div>
            ))}
            {report.bookmarks.length > 0 && (
              <div>
                <div className="group-title">Bookmarks</div>
                {report.bookmarks.map((b) => (
                  <div key={b.id} className="row line">
                    <span className="grow" style={{ paddingLeft: (b.level - 1) * 12 }}>
                      {b.title} <small className="muted">· {b.page !== null ? `page ${b.page}` : "destination gone"}</small>
                      {b.proposed_page !== null && <><br /><small>The heading is on page {b.proposed_page}: re-point there</small></>}
                      {b.proposed_title !== null && <><br /><small>Retitle to "{b.proposed_title}", as the heading reads</small></>}
                      {b.state === "unresolved" && <><br /><small className="muted">Destination gone, and no heading has this title; left as it is.</small></>}
                      {b.state === "unchecked" && <><br /><small className="muted">No heading has this title, so it can't be checked; left as it is.</small></>}
                    </span>
                    <Badge kind={STATE_BADGE[b.state]}>{b.state}</Badge>
                  </div>
                ))}
              </div>
            )}
            {report.unbookmarked.length > 0 && (
              <div>
                <div className="group-title">Headings without a bookmark · {report.unbookmarked.length}</div>
                {report.unbookmarked.map((h, i) => (
                  <div key={i} className="row line">
                    <span className="grow" style={{ paddingLeft: (h.level - 1) * 12 }}>{h.title} <small className="muted">· p. {h.page}</small></span>
                    <button type="button" onClick={() => app.openLinks({ token: report.token, filename: report.filename, page: h.page, pageCount: report.page_count, rect: null })}>Show</button>
                  </div>
                ))}
              </div>
            )}
            {report.unlinked.length > 0 && (
              <div>
                <div className="group-title">References without a link · {report.unlinked.length}</div>
                {report.unlinked.map((u, i) => (
                  <div key={i} className="row line">
                    <span className="grow">{u.reference} <small className="muted">· p. {u.page} → page {u.target_page}</small></span>
                    <button type="button" onClick={() => app.openLinks({ token: report.token, filename: report.filename, page: u.page, pageCount: report.page_count, rect: u.rect })}>Show</button>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

const SCALE = 1.5;   // The server renders pages at this scale (links.page_image)

/** One page of the PDF being checked, as an image, with the link outlined. */
export function LinksPageView({ tab }: { tab: LinksTab }) {
  const app = useApp();
  const [size, setSize] = useState<{ width: number; height: number } | null>(null);
  const image = useLoad(() => Promise.resolve(`/api/links/${tab.token}/pages/${tab.page}`), [tab.token, tab.page]);
  const go = (page: number) => app.openLinks({ token: tab.token, filename: tab.filename, page, pageCount: tab.pageCount, rect: null });
  return (
    <div className="links-page">
      <div className="row toolbar">
        <button type="button" disabled={tab.page <= 1} onClick={() => go(tab.page - 1)}>‹</button>
        <span className="muted">Page {tab.page} of {tab.pageCount}</span>
        <button type="button" disabled={tab.page >= tab.pageCount} onClick={() => go(tab.page + 1)}>›</button>
      </div>
      <div className="links-page-scroll">
        <Status loading={image.loading} error={image.error} />
        {image.data && (
          <div className="links-page-image" style={size ? { width: size.width, height: size.height } : undefined}>
            <img src={image.data} alt={`Page ${tab.page} of ${tab.filename}`}
                 onLoad={(e) => setSize({ width: e.currentTarget.naturalWidth, height: e.currentTarget.naturalHeight })} />
            {tab.rect && size && (
              <div className="links-outline" style={{
                left: tab.rect[0] * SCALE - 3, top: tab.rect[1] * SCALE - 3,
                width: (tab.rect[2] - tab.rect[0]) * SCALE + 6, height: (tab.rect[3] - tab.rect[1]) * SCALE + 6,
              }} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
