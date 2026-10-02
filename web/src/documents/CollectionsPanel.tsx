import { useState } from "react";
import { api } from "../api";
import { useLoad } from "../hooks";
import { useApp } from "../store";
import { Pin } from "../types";
import { Badge, Empty, Icon, Status, Table } from "../ui";

/** Collections of pinned passages, tables, figures and code, with notes; exported to Word or Markdown. */
export function CollectionsPanel() {
  const app = useApp();
  const { collections } = app.overview;
  const collection = collections.find((c) => c.id === app.collectionId);
  const [name, setName] = useState("");
  const [renaming, setRenaming] = useState<string | null>(null);
  const { data, loading, error } = useLoad<{ pins: Pin[] }>(
    () => (collection && app.activity === "collections" ? api.get(`/collections/${collection.id}/pins`) : null),
    [collection?.id, app.pinsVersion, app.activity === "collections"]);

  const create = async () => {
    const created = await app.run(api.post<{ id: number }>("/collections", { name }));
    if (created) {
      setName("");
      await app.refresh();
      app.setCollectionId(created.id);
    }
  };
  const rename = async () => {
    if (collection && renaming !== null && await app.run(api.patch(`/collections/${collection.id}`, { name: renaming }))) {
      setRenaming(null);
      app.refresh();
    }
  };
  const remove = async () => {
    if (collection && window.confirm(`Delete “${collection.name}” and its ${collection.pin_count} pin(s)?`)) {
      await app.run(api.del(`/collections/${collection.id}`));
      app.refresh();
    }
  };

  return (
    <div className="panel">
      <div className="panel-head">
        <div className="row">
          <select className="grow" value={app.collectionId} onChange={(e) => app.setCollectionId(Number(e.target.value))} aria-label="Collection">
            {collections.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.pin_count})</option>)}
          </select>
          <button type="button" onClick={() => setRenaming(collection?.name ?? "")} title="Rename">Rename</button>
          <button type="button" onClick={remove} title="Delete this collection"><Icon name="trash" size={13} /></button>
        </div>
        {renaming !== null && (
          <div className="row">
            <input className="grow" value={renaming} onChange={(e) => setRenaming(e.target.value)} aria-label="New name" />
            <button type="button" className="primary" onClick={rename}>Save</button>
            <button type="button" onClick={() => setRenaming(null)}>Cancel</button>
          </div>
        )}
        <div className="row">
          <input className="grow" value={name} onChange={(e) => setName(e.target.value)} placeholder="New collection, e.g. Pressure relief sizing"
                 onKeyDown={(e) => { if (e.key === "Enter" && name.trim()) create(); }} />
          <button type="button" disabled={!name.trim()} onClick={create}><Icon name="plus" size={13} /> Create</button>
        </div>
        {collection && collection.pin_count > 0 && (
          <div className="row">
            <span className="muted grow">Export with citations</span>
            <a className="link" href={`/api/collections/${collection.id}/export?format=docx`}>Word</a>
            <a className="link" href={`/api/collections/${collection.id}/export?format=md`}>Markdown</a>
          </div>
        )}
      </div>
      <div className="panel-body">
        <Status loading={loading && !data} error={error} />
        {data && !data.pins.length && <Empty>Nothing pinned yet. Use <strong>Pin</strong> on a search result, a passage, a table or a code symbol to collect it here.</Empty>}
        {data?.pins.map((pin) => <PinCard key={pin.id} pin={pin} />)}
      </div>
    </div>
  );
}

function PinCard({ pin }: { pin: Pin }) {
  const app = useApp();
  const [note, setNote] = useState(pin.note);
  const code = pin.kind === "code";
  return (
    <article className="card static">
      <header>
        <Badge kind="page">{code ? "line" : "p."} {pin.page_label}</Badge>
        {pin.label && <Badge kind="object">{pin.label}</Badge>}
        <span className="card-title">{pin.doc_title}</span>
      </header>
      <div className="card-path">{pin.clause}</div>
      <div className="card-body">
        {pin.table ? <Table table={pin.table} /> : code ? <pre className="code">{pin.text}</pre> : <blockquote>{pin.text}</blockquote>}
      </div>
      <textarea value={note} placeholder="Why this matters, open questions…" aria-label="Note"
                onChange={(e) => setNote(e.target.value)}
                onBlur={() => { if (note !== pin.note) app.run(api.patch(`/pins/${pin.id}`, { note })); }} />
      <footer>
        <span className="muted grow">
          {code ? "Source code" : !pin.available ? "Document no longer in the library; text and citation kept" : pin.query ? `Found by “${pin.query}”` : ""}
        </span>
        {!code && (
          <button type="button" disabled={!pin.available || pin.doc_id === null}
                  onClick={() => app.openDoc({ docId: pin.doc_id!, page: pin.page, target: pin.bbox, highlight: pin.query ? { q: pin.query } : {} })}>View page</button>
        )}
        <button type="button" onClick={async () => { await app.run(api.del(`/pins/${pin.id}`)); app.pinsChanged(); }}>Remove</button>
      </footer>
    </article>
  );
}
