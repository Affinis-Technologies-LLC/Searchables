import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, query } from "../api";
import { useDebounced, useLoad } from "../hooks";
import { useApp } from "../store";
import { Codebase, CodeFile, CodeSymbol, Dependencies, Endpoints, Usage } from "../types";
import { Badge, Chips, Empty, Icon, Segments, shortPath, Status } from "../ui";
import { UsageRows } from "./common";
import { forgetFiles } from "./files";

const VIEWS = ["Search", "Files", "Dependencies", "APIs"] as const;
const KINDS: Record<string, string[]> = {
  Types: ["class", "interface", "enum", "record", "annotation", "type"],
  "Methods & functions": ["method", "constructor", "function"],
  "Fields & variables": ["field", "variable"],
};

/** Choose a codebase, then search it, browse its files, or look at its dependencies and HTTP APIs. */
export function CodePanel() {
  const app = useApp();
  const { codebases } = app.overview;
  const [codebaseId, setCodebaseId] = useState<number | null>(null);
  const [view, setView] = useState<(typeof VIEWS)[number]>("Search");
  const [adding, setAdding] = useState(false);
  useEffect(() => {
    if (!codebases.some((c) => c.id === codebaseId)) setCodebaseId(codebases[0]?.id ?? null);
  }, [codebases, codebaseId]);
  const codebase = codebases.find((c) => c.id === codebaseId) ?? null;
  // A finished scan may have renumbered files and symbols: cached file contents are dropped
  useEffect(() => { forgetFiles(); }, [codebase?.indexed_at]);

  const rescan = async () => { if (codebase) { await app.run(api.post(`/codebases/${codebase.id}/scan`)); app.refresh(); } };
  const remove = async () => {
    if (codebase && window.confirm(`Forget “${codebase.name}” and its index? The folder itself isn't touched.`)) {
      await app.run(api.del(`/codebases/${codebase.id}`));
      app.tabs.filter((t) => t.kind === "code").forEach((t) => app.close(t.id));
      app.setSymbolId(null);
      app.refresh();
    }
  };

  return (
    <div className="panel">
      <div className="panel-head">
        {codebases.length > 0 && (
          <div className="row">
            <select className="grow" value={codebaseId ?? ""} onChange={(e) => setCodebaseId(Number(e.target.value))} aria-label="Codebase">
              {codebases.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <button type="button" disabled={!codebase || codebase.scanning} onClick={rescan} title="Read new and changed files again"><Icon name="refresh" size={13} /></button>
            <button type="button" onClick={() => setAdding(!adding)} title="Add a codebase"><Icon name="plus" size={13} /></button>
            <button type="button" disabled={!codebase || codebase.scanning} onClick={remove} title="Remove from the app"><Icon name="trash" size={13} /></button>
          </div>
        )}
        {(adding || !codebases.length) && <AddCodebase onAdded={(id) => { setAdding(false); setCodebaseId(id); }} />}
        {codebase && (
          <div className="muted" title={codebase.root}>
            {codebase.indexed_at
              ? `${codebase.file_count.toLocaleString()} files · ${codebase.symbol_count.toLocaleString()} symbols · scanned ${codebase.indexed_at.replace("T", " ")}`
              : "Being read for the first time…"}{codebase.scanning && codebase.indexed_at ? " · rescanning now" : ""}
          </div>
        )}
        {codebase?.indexed_at && <Segments options={VIEWS} value={view} onChange={setView} />}
      </div>
      {!codebases.length && (
        <div className="panel-body">
          <Empty>Add the top folder of a Java, JavaScript or TypeScript project to browse it: where anything is declared and
            used, what calls what, and which libraries and APIs the code depends on. The folder is read where it is;
            nothing in it is changed.</Empty>
        </div>
      )}
      {codebase?.indexed_at && (
        <>
          {view === "Search" && <CodeSearch codebase={codebase} />}
          {view === "Files" && <FileTree codebase={codebase} />}
          {view === "Dependencies" && <DependenciesView codebase={codebase} />}
          {view === "APIs" && <ApisView codebase={codebase} />}
        </>
      )}
    </div>
  );
}

function AddCodebase({ onAdded }: { onAdded: (id: number) => void }) {
  const app = useApp();
  const [root, setRoot] = useState("");
  const [name, setName] = useState("");
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const added = await app.run(api.post<Codebase>("/codebases", { root, name }));
    if (added) {
      setRoot("");
      setName("");
      await app.refresh();
      onAdded(added.id);
    }
  };
  return (
    <form className="add-codebase" onSubmit={submit}>
      <label>Folder
        <input value={root} onChange={(e) => setRoot(e.target.value)} placeholder={"C:\\Projects\\my-app  or  /Users/me/projects/my-app"}
               title="The top folder of the source code, on the machine this app runs on" />
      </label>
      <label>Name (optional)
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Defaults to the folder's name" />
      </label>
      <button className="primary" type="submit" disabled={!root.trim()}>Add and scan</button>
    </form>
  );
}

function CodeSearch({ codebase }: { codebase: Codebase }) {
  const app = useApp();
  const [mode, setMode] = useState<"Symbols" | "Text">("Symbols");
  const [text, setText] = useState("");
  const [kinds, setKinds] = useState<string[]>([]);
  const wanted = useDebounced(text.trim(), 250);
  const symbols = useLoad<CodeSymbol[]>(
    () => (mode === "Symbols" && wanted ? api.get(`/codebases/${codebase.id}/symbols` + query({ q: wanted, kinds: kinds.flatMap((k) => KINDS[k]) })) : null),
    [codebase.id, codebase.indexed_at, mode, wanted, kinds]);
  const lines = useLoad<{ file_id: number; path: string; line: number; text: string }[]>(
    () => (mode === "Text" && wanted ? api.get(`/codebases/${codebase.id}/text` + query({ q: wanted })) : null),
    [codebase.id, codebase.indexed_at, mode, wanted]);
  return (
    <>
      <div className="panel-head">
        <Segments options={["Symbols", "Text"] as const} value={mode} onChange={setMode} />
        <input type="search" value={text} onChange={(e) => setText(e.target.value)} aria-label="Search the code"
               placeholder={mode === "Symbols" ? "A class, method or function name" : "Any text in the source: a string, a URL, part of a name"} />
        {mode === "Symbols" && <Chips options={Object.keys(KINDS)} value={kinds} onChange={setKinds} />}
      </div>
      <div className="panel-body">
        <Status loading={symbols.loading || lines.loading} error={symbols.error || lines.error} />
        {!wanted && <Empty>Results open in the editor. Choosing a symbol shows its usages, calls and hierarchy on the right.</Empty>}
        {mode === "Symbols" && symbols.data && (
          <>
            <div className="summary"><span>{symbols.data.length} symbol{symbols.data.length === 1 ? "" : "s"}</span></div>
            {symbols.data.map((symbol) => (
              <article key={symbol.id} className={`card ${app.symbolId === symbol.id ? "selected" : ""}`}
                       onClick={() => { app.openCode({ fileId: symbol.file_id, path: symbol.path, line: symbol.line }); app.setSymbolId(symbol.id); app.setAt(null); }}>
                <header><Badge kind="object">{symbol.kind}</Badge><span className="card-title">{symbol.name}</span></header>
                <div className="card-path">{symbol.path}:{symbol.line}</div>
                <code className="signature">{symbol.signature}</code>
              </article>
            ))}
          </>
        )}
        {mode === "Text" && lines.data && (
          <>
            <div className="summary"><span>{lines.data.length} line{lines.data.length === 1 ? "" : "s"}</span></div>
            {lines.data.map((hit, i) => (
              <button key={i} type="button" className="code-row usage" title={hit.path}
                      onClick={() => app.openCode({ fileId: hit.file_id, path: hit.path, line: hit.line })}>
                <span className="where">{shortPath(hit.path, 2)}:{hit.line}</span><code>{hit.text}</code>
              </button>
            ))}
          </>
        )}
      </div>
    </>
  );
}

interface TreeNode { name: string; path: string; folders: Map<string, TreeNode>; files: CodeFile[] }

function buildTree(files: CodeFile[]): TreeNode {
  const root: TreeNode = { name: "", path: "", folders: new Map(), files: [] };
  for (const file of files) {
    const parts = file.path.split("/");
    let node = root;
    for (const part of parts.slice(0, -1)) {
      if (!node.folders.has(part)) node.folders.set(part, { name: part, path: node.path ? `${node.path}/${part}` : part, folders: new Map(), files: [] });
      node = node.folders.get(part)!;
    }
    node.files.push(file);
  }
  return root;
}

function FileTree({ codebase }: { codebase: Codebase }) {
  const app = useApp();
  const { data, loading, error } = useLoad<CodeFile[]>(() => api.get(`/codebases/${codebase.id}/files`), [codebase.id, codebase.indexed_at]);
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const tree = useMemo(() => buildTree(data ?? []), [data]);
  const wanted = filter.trim().toLowerCase();
  const matches = useMemo(() => (wanted ? (data ?? []).filter((f) => f.path.toLowerCase().includes(wanted)).slice(0, 300) : []), [data, wanted]);
  const activeFile = app.active?.kind === "code" ? app.active.fileId : null;

  const toggle = (path: string) => setOpen((current) => {
    const next = new Set(current);
    if (!next.delete(path)) next.add(path);
    return next;
  });
  const fileRow = (file: CodeFile, level: number, label = file.path.split("/").pop()!) => (
    <button key={file.id} type="button" className={`tree-row ${file.id === activeFile ? "on" : ""}`} style={{ paddingLeft: 8 + level * 14 }}
            title={file.path + (file.has_errors ? " · has syntax the parser couldn't fully read" : "")}
            onClick={() => app.openCode({ fileId: file.id, path: file.path, line: 1 })}>
      <Icon name="file" size={13} /> <span className="grow">{label}</span>{file.has_errors && <small className="muted">!</small>}
    </button>
  );
  const folder = (node: TreeNode, level: number): JSX.Element[] => {
    // A chain of folders holding nothing but one folder is shown as one row (src/main/java/com/acme)
    let shown = node, label = node.name;
    while (shown.files.length === 0 && shown.folders.size === 1) {
      shown = [...shown.folders.values()][0];
      label = `${label}/${shown.name}`;
    }
    const expanded = open.has(shown.path);
    return [
      <button key={shown.path} type="button" className="tree-row" style={{ paddingLeft: 8 + level * 14 }} onClick={() => toggle(shown.path)} aria-expanded={expanded}>
        <span className={`twist ${expanded ? "open" : ""}`}><Icon name="chevron" size={12} /></span><Icon name="folder" size={13} /> <span className="grow">{label}</span>
      </button>,
      ...(expanded ? contents(shown, level + 1) : []),
    ];
  };
  const contents = (node: TreeNode, level: number): JSX.Element[] => [
    ...[...node.folders.values()].sort((a, b) => a.name.localeCompare(b.name)).flatMap((child) => folder(child, level)),
    ...node.files.map((file) => fileRow(file, level)),
  ];

  return (
    <>
      <div className="panel-head">
        <input type="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Find a file by part of its path" />
      </div>
      <div className="panel-body tree">
        <Status loading={loading && !data} error={error} />
        {wanted ? matches.map((file) => fileRow(file, 0, shortPath(file.path, 4))) : contents(tree, 0)}
        {wanted && !matches.length && data && <Empty>No file's path contains that.</Empty>}
      </div>
    </>
  );
}

function DependenciesView({ codebase }: { codebase: Codebase }) {
  const [view, setView] = useState<"Declared" | "Used" | "Internal">("Declared");
  const { data, loading, error } = useLoad<Dependencies>(() => api.get(`/codebases/${codebase.id}/dependencies`), [codebase.id, codebase.indexed_at]);
  const [pack, setPack] = useState<string | null>(null);
  const [member, setMember] = useState<string | null>(null);
  const [edge, setEdge] = useState<{ source: string; target: string } | null>(null);
  const detail = useLoad<{ members: { name: string; uses: number }[]; imports: { line: number; spec: string; file_id: number; path: string }[] }>(
    () => (pack ? api.get(`/codebases/${codebase.id}/package` + query({ name: pack })) : null), [codebase.id, pack]);
  const usages = useLoad<Usage[]>(() => (member ? api.get(`/codebases/${codebase.id}/external` + query({ target: member })) : null), [codebase.id, member]);
  const links = useLoad<Usage[]>(() => (edge ? api.get(`/codebases/${codebase.id}/links` + query(edge)) : null), [codebase.id, edge]);
  const app = useApp();
  return (
    <>
      <div className="panel-head">
        <Segments options={["Declared", "Used", "Internal"] as const} value={view} onChange={setView}
                  labels={{ Declared: "Declared libraries", Used: "Outside packages used", Internal: "Between packages" }} />
      </div>
      <div className="panel-body">
        <Status loading={loading && !data} error={error} />
        {data && view === "Declared" && (
          data.declared.length ? (
            <>
              <div className="muted">From the build files. For npm, “Used in” counts the files importing the package: 0 means it's declared but never imported.</div>
              <div className="table-wrap"><table className="data">
                <thead><tr><th>Library</th><th>Version</th><th>Scope</th><th>Used in</th><th>Declared in</th></tr></thead>
                <tbody>{data.declared.map((d, i) => (
                  <tr key={i} className={d.used_in === 0 ? "warn" : ""}><td>{d.name}</td><td>{d.version}</td><td>{d.scope}</td>
                    <td>{d.used_in === null ? "" : `${d.used_in} file${d.used_in === 1 ? "" : "s"}`}</td><td>{d.manifest}</td></tr>
                ))}</tbody>
              </table></div>
            </>
          ) : <Empty>No pom.xml, build.gradle or package.json declares any library.</Empty>
        )}
        {data && view === "Used" && (
          <>
            <div className="muted">Packages imported from outside this codebase. Pick one to see which of its APIs are used, and where.</div>
            <div className="table-wrap short"><table className="data pick">
              <thead><tr><th>Package</th><th>Files</th><th>Uses of its APIs</th></tr></thead>
              <tbody>{data.packages.map((p) => (
                <tr key={p.name} className={p.name === pack ? "on" : ""} onClick={() => { setPack(p.name); setMember(null); }}>
                  <td>{p.name}</td><td>{p.files}</td><td>{p.uses}</td></tr>
              ))}</tbody>
            </table></div>
            <Status loading={detail.loading} error={detail.error} />
            {pack && detail.data && (
              <>
                <div className="group-title">APIs of {pack} in use · {detail.data.members.length}</div>
                {detail.data.members.map((m) => (
                  <div key={m.name}>
                    <button type="button" className={`code-row ${m.name === member ? "on" : ""}`} onClick={() => setMember(m.name === member ? null : m.name)}>
                      <span className="grow"><code>{m.name}</code></span><small className="muted">{m.uses}</small>
                    </button>
                    {m.name === member && usages.data && <div className="nested"><UsageRows usages={usages.data} /></div>}
                  </div>
                ))}
                <div className="group-title">Imported in · {detail.data.imports.length}</div>
                {detail.data.imports.map((item, i) => (
                  <button key={i} type="button" className="code-row usage" title={item.path}
                          onClick={() => app.openCode({ fileId: item.file_id, path: item.path, line: item.line })}>
                    <span className="where">{shortPath(item.path, 2)}:{item.line}</span><code>{item.spec}</code>
                  </button>
                ))}
              </>
            )}
          </>
        )}
        {data && view === "Internal" && (
          data.internal.length ? (
            <>
              <div className="muted">Which package (Java) or folder (JavaScript/TypeScript) refers to which, by linked references. Pick one to see them.</div>
              <div className="table-wrap short"><table className="data pick">
                <thead><tr><th>Package</th><th>Depends on</th><th>References</th></tr></thead>
                <tbody>{data.internal.map((e) => (
                  <tr key={e.source + ">" + e.target} className={edge?.source === e.source && edge.target === e.target ? "on" : ""}
                      onClick={() => setEdge({ source: e.source, target: e.target })}>
                    <td>{e.source}</td><td>{e.target}</td><td>{e.references}</td></tr>
                ))}</tbody>
              </table></div>
              <Status loading={links.loading} error={links.error} />
              {edge && links.data && (
                <>
                  <div className="group-title">{edge.source} → {edge.target} · {links.data.length}</div>
                  <UsageRows usages={links.data} />
                </>
              )}
            </>
          ) : <Empty>No references between packages or folders were linked.</Empty>
        )}
      </div>
    </>
  );
}

function ApisView({ codebase }: { codebase: Codebase }) {
  const app = useApp();
  const { data, loading, error } = useLoad<Endpoints>(() => api.get(`/codebases/${codebase.id}/endpoints`), [codebase.id, codebase.indexed_at]);
  const [filter, setFilter] = useState("");
  const wanted = filter.trim().toLowerCase();
  const served = data?.served.filter((e) => e.route.path.toLowerCase().includes(wanted)) ?? [];
  const unmatched = data?.unmatched.filter((e) => e.path.toLowerCase().includes(wanted)) ?? [];
  return (
    <>
      <div className="panel-head">
        <input type="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter by part of a path, e.g. /users" />
      </div>
      <div className="panel-body">
        <Status loading={loading && !data} error={error} />
        {data && !data.served.length && !data.unmatched.length && (
          <Empty>No HTTP routes (Spring, JAX-RS, Express) or HTTP calls (fetch, axios, $.ajax, http clients) were found.</Empty>
        )}
        {data && (data.served.length > 0 || data.unmatched.length > 0) && (
          <div className="summary"><span>{served.length} route{served.length === 1 ? "" : "s"} served · {served.filter((e) => !e.calls.length).length} with
            no caller found here · {unmatched.length} call{unmatched.length === 1 ? "" : "s"} to routes not served here</span></div>
        )}
        {served.map(({ route, calls }) => (
          <article key={route.id} className="card static">
            <header>
              <Badge kind="page">{route.method}</Badge><span className="card-title">{route.path}</span><span className="muted">{route.framework}</span>
            </header>
            <button type="button" className="code-row" title={route.file_path}
                    onClick={() => { app.openCode({ fileId: route.file_id, path: route.file_path, line: route.line }); if (route.symbol_id) app.setSymbolId(route.symbol_id); }}>
              <span className="grow">Handler: {route.symbol_name || shortPath(route.file_path, 2)}</span><small className="muted">{shortPath(route.file_path, 1)}:{route.line}</small>
            </button>
            {!calls.length && <div className="muted">No caller found in this codebase.</div>}
            {calls.map((call) => (
              <button key={call.id} type="button" className="code-row" title={`${call.framework} call in ${call.symbol_name || call.file_path}`}
                      onClick={() => app.openCode({ fileId: call.file_id, path: call.file_path, line: call.line })}>
                <span className="grow">← {call.method} {call.path}</span><small className="muted">{shortPath(call.file_path, 1)}:{call.line}</small>
              </button>
            ))}
          </article>
        ))}
        {unmatched.length > 0 && <div className="group-title">Calls to routes not served in this codebase · {unmatched.length}</div>}
        {unmatched.map((call) => (
          <button key={call.id} type="button" className="code-row" title={`${call.framework} call in ${call.symbol_name || call.file_path}`}
                  onClick={() => app.openCode({ fileId: call.file_id, path: call.file_path, line: call.line })}>
            <span className="grow">{call.method} {call.path}</span><small className="muted">{shortPath(call.file_path, 1)}:{call.line}</small>
          </button>
        ))}
      </div>
    </>
  );
}
