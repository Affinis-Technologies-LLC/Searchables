// Small pieces used throughout.
import { ReactNode, useState } from "react";

const ICONS: Record<string, string> = {
  search: "M10 4a6 6 0 1 0 3.9 10.6l4.3 4.3 1.4-1.4-4.3-4.3A6 6 0 0 0 10 4zm0 2a4 4 0 1 1 0 8 4 4 0 0 1 0-8z",
  contents: "M4 5h16v2H4zm0 6h10v2H4zm0 6h16v2H4zm13-7 3 2-3 2z",
  catalogue: "M4 4h7v7H4zm9 0h7v7h-7zM4 13h7v7H4zm9 2h7v2h-7zm0 3h5v2h-5z",
  glossary: "M5 3h12a2 2 0 0 1 2 2v16l-4-2-4 2-4-2-4 2V5a2 2 0 0 1 2-2zm2 4v2h8V7zm0 4v2h8v-2z",
  compare: "M3 4h8v16H3zm2 2v12h4V6zm8-2h8v16h-8zm2 2v12h4V6z",
  collections: "M14 4l6 6-4 1-3 3 1 5-5-5-5 5 5-5-5-5 5 1 3-3z",
  library: "M4 4h4v16H4zm6 0h4v16h-4zm6.5.6 3.9 1 -3.6 14.8-3.9-1z",
  code: "M8.6 16.6 4 12l4.6-4.6L10 8.8 6.8 12l3.2 3.2zm6.8 0L14 15.2l3.2-3.2L14 8.8l1.4-1.4L20 12z",
  back: "M14 6l-6 6 6 6 1.4-1.4L10.8 12l4.6-4.6z",
  forward: "M10 6l6 6-6 6-1.4-1.4 4.6-4.6-4.6-4.6z",
  close: "M6.4 5 5 6.4 10.6 12 5 17.6 6.4 19l5.6-5.6 5.6 5.6 1.4-1.4-5.6-5.6L19 6.4 17.6 5 12 10.6z",
  pin: "M14 3l7 7-3 1-3.5 3.5.5 4.5-1.5 1.5-4-4L4 22l-1-1 5.5-5.5-4-4L6 10l4.5.5L14 7z",
  refresh: "M12 5a7 7 0 1 1-6.3 4H3.5A9 9 0 1 0 12 3V1L8 4l4 3z",
  plus: "M11 5h2v6h6v2h-6v6h-2v-6H5v-2h6z",
  trash: "M9 3h6l1 2h4v2H4V5h4zM6 9h12l-1 12H7z",
  file: "M6 2h8l4 4v16H6zm7 1.5V7h3.5z",
  folder: "M3 5h7l2 2h9v12H3z",
  chevron: "M9 6l6 6-6 6z",
  user: "M12 4a4 4 0 1 1 0 8 4 4 0 0 1 0-8zm0 10c4 0 8 2 8 5v1H4v-1c0-3 4-5 8-5z",
  download: "M11 4h2v8l3-3 1.4 1.4L12 15.8 6.6 10.4 8 9l3 3zM5 18h14v2H5z",
  copy: "M8 3h11v13h-2V5H8zM5 7h11v14H5zm2 2v10h7V9z",
  hub: "M12 3a2 2 0 1 1 0 4 2 2 0 0 1 0-4zM5 15a2 2 0 1 1 0 4 2 2 0 0 1 0-4zm14 0a2 2 0 1 1 0 4 2 2 0 0 1 0-4zm-8-7h2v4.4l4.6 2.7-1 1.7L12 14.2l-4.6 2.6-1-1.7 4.6-2.7z",
};

export function Icon({ name, size = 16 }: { name: string; size?: number }) {
  return (
    <svg className="icon" width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path d={ICONS[name] ?? ""} fill="currentColor" />
    </svg>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Status({ loading, error }: { loading: boolean; error: string }) {
  if (error) return <div className="notice error">{error}</div>;
  if (loading) return <div className="loading">Loading…</div>;
  return null;
}

export function Badge({ kind, children, title }: { kind?: string; children: ReactNode; title?: string }) {
  return <span className={`badge ${kind ? "badge-" + kind : ""}`} title={title}>{children}</span>;
}

/** A row of options of which several can be on. */
export function Chips<T extends string>({ options, value, onChange }: { options: T[]; value: T[]; onChange: (value: T[]) => void }) {
  return (
    <div className="chips">
      {options.map((option) => {
        const on = value.includes(option);
        return (
          <button key={option} type="button" className={`chip ${on ? "on" : ""}`} aria-pressed={on}
                  onClick={() => onChange(on ? value.filter((v) => v !== option) : [...value, option])}>
            {option}
          </button>
        );
      })}
    </div>
  );
}

/** A row of options of which one is on. */
export function Segments<T extends string>({ options, value, onChange, labels }: {
  options: readonly T[]; value: T; onChange: (value: T) => void; labels?: Partial<Record<T, string>>;
}) {
  return (
    <div className="segments" role="tablist">
      {options.map((option) => (
        <button key={option} type="button" role="tab" aria-selected={option === value}
                className={option === value ? "on" : ""} onClick={() => onChange(option)}>
          {labels?.[option] ?? option}
        </button>
      ))}
    </div>
  );
}

export function shortPath(path: string, parts = 3): string {
  const pieces = path.split("/");
  return pieces.length > parts ? "…/" + pieces.slice(-parts).join("/") : path;
}

/** Text with every occurrence of the given values wrapped in <mark>, as React nodes (never as HTML). */
export function Marked({ text, values }: { text: string; values: string[] }) {
  const wanted = values.filter(Boolean).sort((a, b) => b.length - a.length);
  if (!wanted.length) return <>{text}</>;
  const pattern = new RegExp(`(${wanted.map((v) => v.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  return <>{text.split(pattern).map((part, i) => (i % 2 ? <mark key={i}>{part}</mark> : part))}</>;
}

/** Puts text on the clipboard. Browsers only offer their clipboard to pages on this machine or over HTTPS, so there's a fallback. */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const done = document.execCommand("copy");
    area.remove();
    return done;
  }
}

/** A button that copies what `text` returns, and says so for a moment. */
export function CopyButton({ text, label = "Copy", title = "Copy to the clipboard", link = false }: {
  text: () => string | Promise<string>; label?: string; title?: string; link?: boolean;
}) {
  const [state, setState] = useState<"" | "done" | "failed">("");
  const copy = async () => {
    setState((await copyText(await text())) ? "done" : "failed");
    setTimeout(() => setState(""), 1500);
  };
  return (
    <button type="button" className={`copy ${link ? "link" : ""} ${state}`} title={title} onClick={(e) => { e.stopPropagation(); copy(); }}>
      <Icon name="copy" size={13} /> {state === "done" ? "Copied" : state === "failed" ? "Couldn't copy" : label}
    </button>
  );
}

/** A table as tab-separated text: pastes into a spreadsheet as cells, and into a document as a table. */
export function tableToTsv(table: { caption?: string; columns: string[]; rows: string[][] }): string {
  const cell = (value: string) => value.replace(/[\t\n\r]+/g, " ");
  return [table.columns, ...table.rows].map((row) => row.map(cell).join("\t")).join("\n");
}

export function Table({ table, highlight = [] }: { table: { caption?: string; columns: string[]; rows: string[][] }; highlight?: string[] }) {
  return (
    <div className="table-wrap">
      <div className="table-head">
        <span className="table-caption grow">{table.caption}</span>
        <CopyButton link label="Copy table" title="Copy as cells, to paste into a spreadsheet or a document"
                    text={() => (table.caption ? table.caption + "\n" : "") + tableToTsv(table)} />
      </div>
      <table className="data">
        <thead><tr>{table.columns.map((c, i) => <th key={i}><Marked text={c} values={highlight} /></th>)}</tr></thead>
        <tbody>
          {table.rows.map((row, r) => <tr key={r}>{row.map((cell, i) => <td key={i}><Marked text={cell} values={highlight} /></td>)}</tr>)}
        </tbody>
      </table>
    </div>
  );
}

export function tableToCsv(table: { columns: string[]; rows: string[][] }): string {
  const cell = (value: string) => (/[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value);
  return [table.columns, ...table.rows].map((row) => row.map(cell).join(",")).join("\n");
}

export function saveText(filename: string, text: string, type = "text/csv"): void {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([text], { type }));
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}
