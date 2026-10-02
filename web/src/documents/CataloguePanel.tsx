import { useEffect, useMemo, useState } from "react";
import { api, query } from "../api";
import { useLoad } from "../hooks";
import { useApp } from "../store";
import { Block, CatalogueChanges, CatalogueDetail, CatalogueEntry, Located } from "../types";
import { Badge, Empty, Status, Table } from "../ui";

const SHOWN = 1200;   // Rows drawn at once; a filter narrows a longer list

/**
 * The documents' identifiers as entries, the way a code browser lists symbols: messages, their words
 * and fields, data elements. An entry gathers where it's introduced, its own tables, the table rows
 * that list it, the rules that mention it, and how it changed between two revisions.
 */
export function CataloguePanel() {
  const app = useApp();
  const { documents } = app.overview;
  const active = app.activity === "catalogue";
  const [docId, setDocId] = useState(0);            // 0: every document
  const [filter, setFilter] = useState("");
  const [pattern, setPattern] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [trail, setTrail] = useState<string[]>([]); // Entries followed; the last one is shown
  const stamp = documents.map((d) => `${d.id}:${d.block_count}`).join(",");
  const scope = query({ docs: docId ? [docId] : undefined });
  const { data, loading, error } = useLoad<CatalogueEntry[]>(() => (active ? api.get(`/catalogue${scope}`) : null), [active, scope, stamp]);

  const wanted = filter.trim().toLowerCase().replace(/[\s_-]+/g, "");
  const patterns = useMemo(() => [...new Set((data ?? []).map((e) => e.pattern))].sort(), [data]);
  const children = useMemo(() => {
    const byParent = new Map<string, CatalogueEntry[]>();
    for (const entry of data ?? []) if (entry.parent) byParent.set(entry.parent, [...(byParent.get(entry.parent) ?? []), entry]);
    return byParent;
  }, [data]);
  const keys = useMemo(() => new Set((data ?? []).map((e) => e.key)), [data]);
  const listed = useMemo(() => (data ?? []).filter((e) =>
    (!pattern || e.pattern === pattern)
    && (wanted ? e.key.toLowerCase().includes(wanted) : pattern ? true : !e.parent || !keys.has(e.parent))), [data, pattern, wanted, keys]);

  const follow = (value: string, restart = false) => setTrail((t) => {
    const at = t.indexOf(value);
    return restart ? [value] : at >= 0 ? t.slice(0, at + 1) : [...t, value].slice(-10);
  });
  const toggle = (key: string) => setOpen((current) => {
    const next = new Set(current);
    if (!next.delete(key)) next.add(key);
    return next;
  });

  const row = (entry: CatalogueEntry, level: number): JSX.Element[] => {
    const kids = wanted || pattern ? [] : children.get(entry.key) ?? [];
    return [
      <div key={entry.key} className="entry-row row" style={{ paddingLeft: level * 14 }}>
        {kids.length > 0
          ? <button type="button" className="link" onClick={() => toggle(entry.key)} aria-expanded={open.has(entry.key)} title="Show its parts">{open.has(entry.key) ? "▾" : "▸"}</button>
          : <span style={{ width: 14 }} />}
        <span className={`dot ${entry.defined ? "" : "off"}`} title={entry.defined ? "Introduced by a heading or caption" : "Mentioned only"} />
        <button type="button" className="code-row" onClick={() => follow(entry.value, true)}>
          <span className="grow">{entry.value}</span>
          <small className="muted">{kids.length > 0 && `${kids.length} parts · `}{entry.passages}</small>
        </button>
      </div>,
      ...(open.has(entry.key) ? kids.flatMap((kid) => row(kid, level + 1)) : []),
    ];
  };

  if (!documents.length) return <Empty>Add documents in Library to browse their identifiers.</Empty>;
  const current = trail[trail.length - 1];
  return (
    <div className="panel">
      <div className="panel-head">
        <select value={docId} onChange={(e) => { setDocId(Number(e.target.value)); setTrail([]); }} aria-label="Documents">
          <option value={0}>All documents</option>
          {documents.map((d) => <option key={d.id} value={d.id}>{d.title}</option>)}
        </select>
        {!current && (
          <div className="row">
            <input className="grow" type="search" value={filter} onChange={(e) => setFilter(e.target.value)}
                   placeholder="Filter: M3.2, GRP 281…" aria-label="Filter identifiers" />
            <select value={pattern} onChange={(e) => setPattern(e.target.value)} aria-label="Pattern" title="# stands for any number">
              <option value="">All patterns</option>
              {patterns.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
        )}
        {current && (
          <div className="crumbs">
            <button type="button" onClick={() => setTrail([])}>← All</button>
            {trail.map((value, i) => (
              <span key={value}>{i > 0 && <span className="muted"> › </span>}
                <button type="button" className="link" disabled={i === trail.length - 1} onClick={() => follow(value)}>{value}</button></span>
            ))}
          </div>
        )}
      </div>
      <div className="panel-body">
        {!current && (
          <>
            <Status loading={loading && !data} error={error} />
            {data && !data.length && (
              <Empty>No identifiers yet. They're discovered per document; switch patterns on under Library → Manage → Identifiers.</Empty>
            )}
            {data && data.length > 0 && (
              <div className="summary"><span>{listed.length.toLocaleString()} {wanted || pattern ? "matching" : "top-level"} of {data.length.toLocaleString()} identifiers</span>
                <span title="A filled dot: a heading or caption introduces it">● introduced</span></div>
            )}
            {listed.slice(0, SHOWN).flatMap((entry) => row(entry, 0))}
            {listed.length > SHOWN && <div className="muted">Showing the first {SHOWN}; filter to narrow them.</div>}
          </>
        )}
        {current && <Entry value={current} scope={scope} onFollow={follow} />}
      </div>
    </div>
  );
}

function Entry({ value, scope, onFollow }: { value: string; scope: string; onFollow: (value: string) => void }) {
  const app = useApp();
  const { data, loading, error } = useLoad<CatalogueDetail>(
    () => api.get(`/catalogue/entry` + query({ id: value }) + scope.replace("?", "&")), [value, scope]);
  const openBlock = (block: Block) => block.doc_id !== null && app.openDoc({
    docId: block.doc_id, page: block.page, target: block.bbox, blockId: block.id, highlight: { identifier: value },
  });
  const where = (item: Located) => `${data && data.documents.length > 1 ? item.doc_title + " · " : ""}${item.block.label || item.block.clause || "Passage"} · p. ${item.block.display_page}`;
  const chips = (title: string, values: string[], hint: string) => values.length > 0 && (
    <section>
      <div className="group-title" title={hint}>{title} · {values.length}</div>
      <div className="row wrap">{values.map((v) => <button key={v} type="button" className="link" onClick={() => onFollow(v)}>{v}</button>)}</div>
    </section>
  );
  if (!data) return <Status loading={loading} error={error} />;
  const nothing = !data.defined.length && !data.tables.length && !data.rows.length && !data.rules.length && !data.mentions;
  return (
    <>
      <h3 className="card-title">{data.value || value}</h3>
      {nothing && <Empty>Nothing in scope mentions it. Its pattern may be switched off (Library → Manage → Identifiers).</Empty>}
      {data.parent && chips("Part of", [data.parent], "The identifier this one extends")}
      {chips("Its parts", data.children, "Identifiers that extend this one: a message's words, a data field's uses")}
      {data.defined.length > 0 && (
        <section>
          <div className="group-title">Introduced in · {data.defined.length}</div>
          {data.defined.map((item) => (
            <button key={item.block.id} type="button" className="code-row usage" onClick={() => openBlock(item.block)}>
              <span className="where">{where(item)}</span><span>{item.block.text.slice(0, 160)}</span>
            </button>
          ))}
        </section>
      )}
      {data.tables.map((table) => (
        <section key={table.block.id}>
          <div className="group-title">Its table</div>
          <button type="button" className="link" onClick={() => openBlock(table.block)}>{where(table)}</button>
          {table.pages && table.pages.length > 1 && <span className="muted"> · joined from pages {table.pages.join(", ")}</span>}
          <Table table={table} />
        </section>
      ))}
      {chips("Contains", data.contains, "Identifiers listed in its own tables: a word's fields, a message's data elements")}
      {chips("Used by", data.used_by, "Whose tables and rules list it")}
      {data.rows.length > 0 && (
        <section>
          <div className="group-title">Listed in · {data.rows.length}</div>
          {data.rows.map((item, i) => (
            <article key={i} className="card" onClick={() => openBlock(item.block)}>
              <header>{item.owners.map((o) => <Badge key={o} kind="object">{o}</Badge>)}<span className="card-path">{where(item)}</span></header>
              <dl className="record">
                {item.columns.map((column, c) => item.cells[c] ? [<dt key={`t${c}`}>{column || `Column ${c + 1}`}</dt>, <dd key={`d${c}`}>{item.cells[c]}</dd>] : null)}
              </dl>
            </article>
          ))}
        </section>
      )}
      {data.rules.length > 0 && (
        <section>
          <div className="group-title">Rules that mention it · {data.rules.length}</div>
          {data.rules.map((item) => (
            <button key={item.block.id} type="button" className="code-row usage" onClick={() => openBlock(item.block)}>
              <span className="where">{where(item)} · {item.block.provision}</span><span>{item.block.text.slice(0, 260)}</span>
            </button>
          ))}
        </section>
      )}
      {chips("Appears with", data.related.map((r) => r.value), "Identifiers sharing a table row or passage with it")}
      {data.mentions > 0 && <div className="muted">Also mentioned in {data.mentions} other passage{data.mentions === 1 ? "" : "s"} (search for it with Identifier on to list them).</div>}
      {app.overview.documents.length > 1 && <Changes value={value} />}
    </>
  );
}

function RowTable({ rows }: { rows: { columns: string[]; cells: string[] }[] }) {
  return <Table table={{ columns: rows[0].columns, rows: rows.map((r) => r.cells) }} />;
}

function Changes({ value }: { value: string }) {
  const app = useApp();
  const { documents } = app.overview;
  const [older, setOlder] = useState(0);
  const [newer, setNewer] = useState(0);
  useEffect(() => { setOlder(0); setNewer(0); }, [value]);
  const ready = older > 0 && newer > 0 && older !== newer;
  const { data, loading, error } = useLoad<CatalogueChanges>(
    () => (ready ? api.get(`/catalogue/changes` + query({ id: value, old: older, new: newer })) : null), [value, older, newer, ready]);
  const pick = (current: number, set: (id: number) => void, label: string) => (
    <select className="grow" value={current} onChange={(e) => set(Number(e.target.value))} aria-label={label}>
      <option value={0}>{label}…</option>
      {documents.map((d) => <option key={d.id} value={d.id}>{d.title}</option>)}
    </select>
  );
  const rule = (block: Block, kind: string) => (
    <button key={block.id} type="button" className="code-row usage"
            onClick={() => block.doc_id !== null && app.openDoc({ docId: block.doc_id, page: block.page, target: block.bbox, blockId: block.id, highlight: { identifier: value } })}>
      <span className="where">{kind} · p. {block.display_page}</span><span>{block.text.slice(0, 260)}</span>
    </button>
  );
  const same = data && !data.added.length && !data.removed.length && !data.changed.length && !data.rules_added.length && !data.rules_removed.length;
  return (
    <section>
      <div className="group-title" title="Rows of its own tables added, removed or changed, and rules in only one of the two">Changes between two revisions</div>
      <div className="row">{pick(older, setOlder, "Older")}{pick(newer, setNewer, "Newer")}</div>
      <Status loading={loading} error={error} />
      {data && (!data.in_old || !data.in_new) && <div className="notice">{value} isn't in the {data.in_old ? "newer" : "older"} document{!data.in_old && !data.in_new ? "s" : ""}.</div>}
      {same && data.in_old && data.in_new && <div className="muted">No differences found: {data.unchanged} table row{data.unchanged === 1 ? "" : "s"} the same, and the same rules.</div>}
      {data && data.changed.length > 0 && (
        <>
          <div className="muted">{data.changed.length} row{data.changed.length === 1 ? "" : "s"} changed ({data.unchanged} unchanged)</div>
          <div className="table-wrap"><table className="data">
            <thead><tr><th />{data.changed[0].columns.map((c, i) => <th key={i}>{c}</th>)}</tr></thead>
            <tbody>
              {data.changed.flatMap((change, r) => [
                <tr key={`o${r}`}><td className="muted">was</td>{change.old.map((cell, i) => <td key={i} className={cell !== change.new[i] ? "diff-del" : ""}>{cell}</td>)}</tr>,
                <tr key={`n${r}`}><td className="muted">now</td>{change.new.map((cell, i) => <td key={i} className={cell !== change.old[i] ? "diff-ins" : ""}>{cell}</td>)}</tr>,
              ])}
            </tbody>
          </table></div>
        </>
      )}
      {data && data.added.length > 0 && <><div className="muted">{data.added.length} row{data.added.length === 1 ? "" : "s"} added</div><RowTable rows={data.added} /></>}
      {data && data.removed.length > 0 && <><div className="muted">{data.removed.length} row{data.removed.length === 1 ? "" : "s"} removed</div><RowTable rows={data.removed} /></>}
      {data?.rules_removed.map((b) => rule(b, "Only in the older"))}
      {data?.rules_added.map((b) => rule(b, "Only in the newer"))}
    </section>
  );
}
