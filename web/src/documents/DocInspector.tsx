import { useMemo, useState } from "react";
import { api } from "../api";
import { useLoad } from "../hooks";
import { DocTab, useApp } from "../store";
import { Block, PageData, Related, RelatedItem } from "../types";
import { Badge, CopyButton, Empty, Icon, saveText, Segments, Status, Table, tableToCsv } from "../ui";
import { usePage } from "./pages";

const VIEWS = ["Related", "Page", "Tables", "References", "Terms"] as const;
const FINDING_KIND: Record<string, string> = {
  "Possible conflict": "conflict", "Stronger requirement": "change", "Weaker requirement": "change",
  "Different value": "change", "Different identifiers": "info", "Same content": "same",
};

/** Beside the page: what the explored passage connects to, and the page's text, tables, references and terms. */
export function DocInspector({ tab }: { tab: DocTab }) {
  const [view, setView] = useState<(typeof VIEWS)[number]>("Related");
  const { data, loading, error } = usePage(tab.docId, tab.page, tab.highlight);
  const counts = data ? {
    Tables: data.blocks.filter((b) => b.kind === "table" || b.kind === "figure").length,
    References: data.references.length + data.referenced_by.length,
    Terms: data.terms.length,
  } : null;
  const labels = Object.fromEntries(VIEWS.map((v) => [v, counts && v in counts && counts[v as keyof typeof counts]
    ? `${v} (${counts[v as keyof typeof counts]})` : v])) as Record<(typeof VIEWS)[number], string>;
  // The passage being explored: the one chosen, else the first body passage on the page
  const focus = data?.blocks.find((b) => b.id === tab.blockId) ?? data?.blocks.find((b) => b.kind !== "heading") ?? data?.blocks[0] ?? null;

  return (
    <div className="panel">
      <div className="panel-head"><Segments options={VIEWS} value={view} onChange={setView} labels={labels} /></div>
      <div className="panel-body">
        <Status loading={loading && !data} error={error} />
        {data && view === "Related" && <RelatedView tab={tab} focus={focus} />}
        {data && view === "Page" && <PageText tab={tab} data={data} focusId={focus?.id ?? null} />}
        {data && view === "Tables" && <Objects tab={tab} data={data} />}
        {data && view === "References" && <References tab={tab} data={data} />}
        {data && view === "Terms" && <Terms tab={tab} data={data} />}
      </div>
    </div>
  );
}

function name(block: Block): string {
  return block.label || block.clause || (block.text.length > 60 ? block.text.slice(0, 60) + "…" : block.text);
}

function RelatedView({ tab, focus }: { tab: DocTab; focus: Block | null }) {
  const app = useApp();
  const { data, loading, error } = useLoad<Related>(() => (focus ? api.get(`/blocks/${focus.id}/related`) : null), [focus?.id]);
  if (!focus) return <Empty>Open a page to explore what's related to its passages.</Empty>;
  const pinned = !!focus.pin_key && app.pinned.has(focus.pin_key);
  return (
    <>
      <div className="exploring">
        <div className="grow">Exploring <strong>{name(focus)}</strong> · p. {focus.display_page}
          <div className="muted">Click a passage on the page to explore it instead.</div></div>
        <CopyButton text={() => app.passageText(focus, app.overview.documents.find((d) => d.id === focus.doc_id)?.title ?? "")}
                    title="Copy this passage" />
        <button type="button" className={pinned ? "on" : ""} onClick={() => app.togglePin(focus, tab.highlight.q ?? tab.highlight.identifier)}>
          <Icon name="pin" size={13} /> {pinned ? "Pinned" : "Pin"}
        </button>
      </div>
      <Status loading={loading} error={error} />
      {data && !data.groups.length && <Empty>Nothing related found: no references, shared identifiers, defined terms or similar wording.</Empty>}
      {data?.groups.map((group) => (
        <section key={group.key}>
          <div className="group-title">{group.title} · {group.items.length}</div>
          {group.items.map((item) => <RelatedRow key={item.block.id} item={item} tab={tab} />)}
        </section>
      ))}
    </>
  );
}

function RelatedRow({ item, tab }: { item: RelatedItem; tab: DocTab }) {
  const app = useApp();
  const { block } = item;
  const preview = item.closest ? item.closest[1] : block.text;
  const open = () => block.doc_id !== null && app.openDoc({
    docId: block.doc_id, page: block.page, target: block.bbox, blockId: block.id,
    highlight: block.doc_id === tab.docId ? tab.highlight : {},
  });
  return (
    <details className="related">
      <summary>
        <button type="button" className="link" onClick={(e) => { e.preventDefault(); open(); }}
                title="Open this passage and explore what it's related to">
          {block.doc_id !== tab.docId && `${item.doc_title} · `}{block.label || block.clause || "Passage"} · p. {block.display_page}
        </button>
        <div className="findings">
          {item.findings.length
            ? item.findings.map((f, i) => (
              <Badge key={i} kind={"finding-" + (FINDING_KIND[f.label] ?? "info")} title={f.detail}>
                {f.label}{f.detail && f.label !== "Different identifiers" ? `: ${f.detail}` : ""}
              </Badge>
            ))
            : <span className="reason">{item.reason}</span>}
        </div>
        <div className="preview">{preview}</div>
      </summary>
      {item.closest && (
        <div className="pair">
          <div><small>This passage</small>{item.closest[0]}</div>
          <div><small>That passage</small>{item.closest[1]}</div>
        </div>
      )}
      {item.findings.filter((f) => f.detail).map((f, i) => <div key={i} className="muted"><strong>{f.label}:</strong> {f.detail}</div>)}
      <p>{block.text}</p>
      <CopyButton text={() => app.passageText(block, item.doc_title)} title="Copy this passage" />
    </details>
  );
}

function PageText({ tab, data, focusId }: { tab: DocTab; data: PageData; focusId: number | null }) {
  const app = useApp();
  if (!data.blocks.length) return <Empty>No text on this page.</Empty>;
  return (
    <>
      {data.blocks.map((block) => {
        const table = block.kind === "table" ? data.tables[block.id] : null;
        const html = data.matches[block.id];
        return (
          <div key={block.id} className={`page-block ${block.kind} ${html ? "hit" : ""} ${block.id === focusId ? "focus" : ""}`}
               onClick={() => app.updateDoc(tab.id, { blockId: block.id, target: null, nonce: tab.nonce + 0.001 })}
               title="Explore this passage">
            {table ? <Table table={table} />
              : block.kind === "figure" ? <em>[{block.text}]</em>
              : html ? <span dangerouslySetInnerHTML={{ __html: html }} /> : block.text}
          </div>
        );
      })}
    </>
  );
}

function Objects({ tab, data }: { tab: DocTab; data: PageData }) {
  const app = useApp();
  const objects = data.blocks.filter((b) => b.kind === "table" || b.kind === "figure");
  const doc = app.overview.documents.find((d) => d.id === tab.docId);
  if (!objects.length) return <Empty>No tables or figures detected on this page.</Empty>;
  return (
    <>
      {objects.map((block) => <ObjectCard key={block.id} block={block} tab={tab} title={doc?.title ?? ""} />)}
    </>
  );
}

function ObjectCard({ block, tab, title }: { block: Block; tab: DocTab; title: string }) {
  const app = useApp();
  // A table continued over several pages is shown (and downloaded) joined
  const joined = useLoad(() => (block.kind === "table" ? api.get<{ caption: string; columns: string[]; rows: string[][]; pages: number[] }>(`/blocks/${block.id}/table`) : null), [block.id]);
  const pinned = !!block.pin_key && app.pinned.has(block.pin_key);
  return (
    <div className="card static">
      <header>
        <span className="card-title">{block.label || `Untitled ${block.kind}`}</span>
        <span className="grow" />
        <button type="button" className={pinned ? "on" : ""} onClick={() => app.togglePin(block)}><Icon name="pin" size={13} /> {pinned ? "Pinned" : "Pin"}</button>
        <button type="button" onClick={() => app.updateDoc(tab.id, { target: block.bbox, blockId: block.id, nonce: tab.nonce + 0.001 })}>Show on page</button>
      </header>
      {block.kind === "figure" && <div className="card-body"><em>{block.text}</em></div>}
      {joined.data && (
        <>
          {joined.data.pages.length > 1 && <div className="muted">Joined from pages {joined.data.pages.join(", ")}</div>}
          <Table table={joined.data} />
          <button type="button" className="link" onClick={() => saveText(`${title} ${block.label || "table"}.csv`, tableToCsv(joined.data!))}>
            <Icon name="download" size={13} /> CSV
          </button>
        </>
      )}
    </div>
  );
}

function References({ tab, data }: { tab: DocTab; data: PageData }) {
  const app = useApp();
  return (
    <>
      <div className="group-title">Referenced on this page</div>
      {!data.references.length && <div className="muted">None found.</div>}
      {data.references.map((ref, i) => {
        const where = ref.doc_id === null ? (ref.kind === "standard" ? "not in the library" : "not found in this document")
          : ref.doc_id !== tab.docId ? `opens ${ref.doc_title}` : `page ${ref.page}`;
        return (
          <div key={i} className="row line">
            <span className="grow">{ref.kind === "clause" ? `Clause ${ref.target}` : ref.target} <small className="muted">· {where}</small></span>
            <button type="button" disabled={ref.doc_id === null}
                    onClick={() => app.openDoc({ docId: ref.doc_id!, page: ref.page ?? 1, target: ref.bbox, blockId: ref.block_id,
                                                 highlight: ref.doc_id === tab.docId ? tab.highlight : {} })}>Go</button>
          </div>
        );
      })}
      <div className="group-title">Refers to this page</div>
      {!data.referenced_by.length && <div className="muted">Nothing elsewhere in this document refers to the clauses, tables or figures on this page.</div>}
      {data.referenced_by.map((ref, i) => (
        <div key={i} className="row line">
          <span className="grow">
            {ref.kind === "clause" ? `Clause ${ref.target}` : ref.target} ← {ref.block.label || ref.block.clause || "Untitled passage"}, page {ref.block.page}
            <br /><small className="muted">{ref.block.text.slice(0, 140)}{ref.block.text.length > 140 ? "…" : ""}</small>
          </span>
          <button type="button" onClick={() => app.openDoc({ docId: tab.docId, page: ref.block.page, target: ref.block.bbox,
                                                             blockId: ref.block.id, highlight: tab.highlight })}>Go</button>
        </div>
      ))}
    </>
  );
}

function Terms({ tab, data }: { tab: DocTab; data: PageData }) {
  const app = useApp();
  const terms = useMemo(() => data.terms, [data]);
  if (!terms.length) return <Empty>No terms defined in this document's terms and definitions clause appear on this page.</Empty>;
  return (
    <>
      {terms.map((term) => (
        <div key={term.clause_num + term.term} className="row line">
          <span className="grow">
            <strong>{term.term}</strong>{term.synonyms.length > 0 && <small className="muted"> (also: {term.synonyms.join(", ")})</small>}
            <small className="muted"> · {term.clause_num}</small><br />{term.definition}
          </span>
          <button type="button" title="Open where this term is defined"
                  onClick={() => app.openDoc({ docId: term.doc_id, page: term.page, target: term.bbox, highlight: tab.highlight })}>Go</button>
        </div>
      ))}
    </>
  );
}
