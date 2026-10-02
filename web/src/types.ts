// The shapes the server's API returns (see src/server/app.py).

export type BBox = [number, number, number, number];

export interface Block {
  id: number;
  doc_id: number | null;
  page: number;
  page_label: string;
  display_page: string;
  text: string;
  kind: "text" | "heading" | "table" | "figure" | "code";
  label: string;
  clause_num: string;
  clause_title: string;
  clause_path: string;
  clause: string;
  bbox: BBox | null;
  provision: "" | "requirement" | "recommendation" | "permission" | "note";
  pin_key: string | null;
}

export interface DocumentInfo {
  id: number;
  title: string;
  filename: string;
  page_count: number;
  block_count: number;
  ocr_pages: number;
  added_at: string;
  outdated: boolean;
  meaning: boolean;
  busy: boolean;
  distribution: string;     // Its distribution statement, as printed ("" when none was found)
}

export interface Collection { id: number; name: string; pin_count: number }

export interface Codebase {
  id: number;
  name: string;
  root: string;
  indexed_at: string;
  file_count: number;
  symbol_count: number;
  scanning: boolean;
}

export interface Job {
  id: number;
  kind: "add" | "reindex" | "embed" | "code";
  name: string;
  status: "queued" | "running" | "done" | "failed";
  stage: string;
  done: number;
  total: number;
  result: string;
  warning: string;
}

export interface Overview {
  documents: DocumentInfo[];
  collections: Collection[];
  codebases: Codebase[];
  jobs: { active: Job[]; finished: Job[] };
  recent: string[];
  ocr: boolean;
  meaning_model: boolean;
  content_kinds: Record<string, string[]>;
  provisions: Record<string, string>;
  max_results: number;
}

export interface Term {
  term: string;
  synonyms: string[];
  clause_num: string;
  definition: string;
  doc_id: number;
  page: number;
  bbox: BBox | null;
  acronym: boolean;         // From a list of acronyms: "definition" is what it stands for
}

export interface TableData { caption: string; columns: string[]; rows: string[][]; pages?: number[] }

export interface SearchResult {
  block: Block;
  doc_title: string;
  html: string;
  match: "keyword" | "some" | "meaning" | "both";
  similarity: number | null;
  score: number;
  citation: string;
  table: TableData | null;
  terms: Term[];
}

export interface IdentifierHit {
  block: Block;
  doc_title: string;
  group: string;
  values: string[];
  html: string | null;
  table: TableData | null;
  citation: string;
}

export interface IdentifierResults {
  key: string;
  hits: IdentifierHit[];
  groups: Record<string, string>;
  related: {
    parent: string | null;
    children: string[];
    related: { key: string; value: string; same_row: number; same_passage: number }[];
  };
  suggestions: string[];
  outdated: number;
}

export interface PageData {
  page: number;
  page_label: string;
  blocks: Block[];
  matches: Record<string, string>;
  hits: BBox[];
  hit_pages: number[];
  tables: Record<string, TableData | null>;
  references: { kind: string; target: string; doc_id: number | null; page: number | null; bbox: BBox | null;
                doc_title: string; block_id: number | null }[];
  referenced_by: { kind: string; target: string; block: Block }[];
  terms: Term[];
}

export interface Finding { label: string; detail: string }

export interface RelatedItem {
  block: Block;
  doc_title: string;
  reason: string;
  similarity: number | null;
  findings: Finding[];
  closest: [string, string] | null;
}

export interface Related { block: Block; doc_title: string; groups: { key: string; title: string; items: RelatedItem[] }[] }

export interface OutlineEntry { block_id: number; page: number; num: string; title: string; level: number; bbox: BBox | null }

export interface Pin {
  id: number;
  doc_id: number | null;
  doc_title: string;
  page: number;
  page_label: string;
  kind: string;
  label: string;
  clause: string;
  citation: string;
  text: string;
  note: string;
  query: string;
  bbox: BBox | null;
  table: TableData | null;
  available: boolean;
  marking: string;
}

export interface ClauseSide { num: string; title: string; page: number; bbox: BBox | null; text: string }

export interface ClauseDiff {
  status: "changed" | "added" | "removed" | "unchanged";
  renumbered: boolean;
  similarity: number;
  provision_change: string;
  old: ClauseSide | null;
  new: ClauseSide | null;
  html: string | null;
}

export interface Comparison {
  counts: Record<string, number>;
  renumbered: number;
  provision_changes: number;
  diffs: ClauseDiff[];
}

export interface IdentifierFamily {
  family: string;
  display: string;
  distinct_values: number;
  passages: number;
  examples: string;
  auto_enabled: boolean;
  user_enabled: boolean | null;
  enabled: boolean;
}

// ---- Source code

export interface CodeFile { id: number; codebase_id: number; path: string; language: string; lines: number; has_errors: boolean }

export interface CodeSymbol {
  id: number;
  codebase_id: number;
  file_id: number;
  parent_id: number | null;
  kind: string;
  name: string;
  qualified: string;
  line: number;
  end_line: number;
  signature: string;
  params: number;
  exported: boolean;
  path: string;
  language: string;
}

export interface Usage {
  ref_id: number;
  kind: string;
  name: string;
  line: number;
  col: number;
  file_id: number;
  path: string;
  text: string;
  from_symbol: number | null;
  from_name: string;
  certainty: "resolved" | "supertype" | "name";
  target_id: number | null;
  target: string;
}

export interface CallNode { symbol: CodeSymbol; line: number; children: CallNode[]; truncated: boolean }

export interface FileDetail {
  file: CodeFile;
  text: string;
  outline: CodeSymbol[];
  imports: { line: number; spec: string; target_file: number | null; target_path: string | null; external: string }[];
  imported_by: { line: number; spec: string; file_id: number; path: string }[];
}

export interface At { ref: Usage | null; target: CodeSymbol | null; declared: CodeSymbol | null; candidates: CodeSymbol[] }

export interface SymbolDetail {
  symbol: CodeSymbol;
  members: CodeSymbol[];
  hierarchy: {
    supertypes: CodeSymbol[];
    external_supertypes: string[];
    subtypes: CodeSymbol[];
    overrides: CodeSymbol[];
    overridden_by: CodeSymbol[];
  };
}

export interface Calls { tree: CallNode[]; depth: number; outside: Usage[]; unlinked: Usage[] }

export interface Dependencies {
  declared: { manifest: string; ecosystem: string; name: string; version: string; scope: string; used_in: number | null }[];
  packages: { name: string; files: number; uses: number }[];
  internal: { source: string; target: string; references: number }[];
}

export interface EndpointInfo {
  id: number;
  side: string;
  method: string;
  path: string;
  line: number;
  file_id: number;
  file_path: string;
  symbol_id: number | null;
  symbol_name: string;
  framework: string;
}

export interface Endpoints { served: { route: EndpointInfo; calls: EndpointInfo[] }[]; unmatched: EndpointInfo[] }

// ---- Catalogue of identifiers (messages, words, data elements…)

export interface CatalogueEntry { key: string; value: string; pattern: string; passages: number; defined: boolean; parent: string | null }

export interface Located { block: Block; doc_title: string }

export interface CatalogueDetail {
  key: string;
  value: string;
  defined: Located[];
  tables: (Located & TableData)[];
  rows: (Located & { owners: string[]; columns: string[]; cells: string[] })[];
  rules: Located[];
  mentions: number;
  contains: string[];
  used_by: string[];
  parent: string | null;
  children: string[];
  related: { key: string; value: string; same_row: number; same_passage: number }[];
  documents: { id: number; title: string }[];
}

export interface CatalogueChanges {
  value: string;
  added: { columns: string[]; cells: string[] }[];
  removed: { columns: string[]; cells: string[] }[];
  changed: { columns: string[]; old: string[]; new: string[] }[];
  unchanged: number;
  rules_added: Block[];
  rules_removed: Block[];
  in_old: boolean;
  in_new: boolean;
}

export interface HealthCheck { name: string; value: string; note: string; warn: boolean }
