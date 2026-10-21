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
  resumed: boolean;      // Left unfinished by an earlier run of the app and picked up at start-up
  restarted: boolean;    // A resumed add stopped during reading: its pages are read again from the first
}

export interface Overview {
  version: string;
  commit: string;
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

export interface CodeFile { id: number; codebase_id: number; path: string; language: string; lines: number; has_errors: boolean; sha256: string }

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
  type: string;             // Declared or return type, as written
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
  certainty: "resolved" | "supertype" | "rule" | "name";
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
  editable?: boolean;
}

/** The server's answer to a save, rename or creation: the file and its new outline. */
export type SavedFile = Omit<FileDetail, "text">;

// ---- Examples as you type (ADR-012)

export interface Expression { kind: string; name: string; partial: string; receiver: string; args_so_far: number; chain: string; start_col: number }
export interface TypeRef { id: number | null; qualified: string; path: string; certainty: string; carried: string }
export interface Enclosing { id: number | null; kind: string; qualified: string; name: string; type: string; package: string; line: number; end_line: number; type_id: number | null }
export interface ExampleContext {
  file_id: number;
  language: string;
  digest: string;
  expression: Expression;
  enclosing: Enclosing | null;
  receiver_type: TypeRef | null;
  neighbours: { calls: string[]; types: string[]; shape: string };
}
export interface Example {
  ref_id: number;
  file_id: number;
  path: string;
  line: number;
  col: number;
  start: number;
  end: number;
  lines: string[];
  first_line: number;
  statement: string;
  enclosing: string;
  enclosing_id: number | null;
  target: string;
  certainty: string;
  features: Record<string, number>;
  score: number;
  reason: string;
}
export interface ExamplesAnswer { context: ExampleContext; filter: string; by_name: boolean; weights: Record<string, number>; examples: Example[] }
export interface CompletionItem {
  name: string; kind: string; params: number; signature: string; type: string; examples: number; detail: string;
  insert_import: string | null; symbol_id: number | null;
}

export interface About {
  version: string; commit: string; checkout: boolean; data_dir: string;
  model: { name: string; revision: string; dir: string; present: boolean; device: string };
  ocr: boolean; python: string; platform: string;
  counts: { documents: number; codebases: number; collections: number; pins: number };
  python_packages: { name: string; version: string; licence: string }[];
}

export interface ReplacePreview { changes: { file_id: number; path: string; sha256: string; count: number; text: string }[] }

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

// ---- Patterns (ADR-013)

export interface Where { file_id: number; path: string; line: number; enclosing: string }
export interface PatternMember { name: string; calls: number; examples: Where[] }
export interface PatternPair { first: string; second: string; methods: number; examples: Where[]; support: number; confidence: number; of: number }
export interface Idiom { type_id: number; type_name: string; qualified: string; call_sites: number; members: PatternMember[]; pairs: PatternPair[] }
export interface Made { type_id: number; type_name: string; qualified: string; constructed: number; injected: number; factory: number; examples: Where[] }
export interface ChainNode { symbol: string; symbol_id: number; line: number; children: ChainNode[] }
export interface EntryPoint { route: string; handler: string; handler_id: number | null; file_id: number; path: string; line: number; chain: ChainNode[] }
export interface HotSymbol { symbol_id: number; name: string; qualified: string; kind: string; references: number; examples: Where[] }
export interface HotFile { file_id: number; path: string; references: number }
export interface Naming { package: string; suffix: string; count: number; total: number; examples: Where[] }
export interface Raised { type_name: string; count: number; examples: Where[] }
export interface AngularComponent {
  symbol_id: number; name: string; selector: string; template: string; inputs: string[]; outputs: string[]; injected: string[]; renders: string[];
  file_id: number; path: string; line: number;
}
export interface ReactComponent { symbol_id: number; name: string; renders: string[]; hooks: string[]; file_id: number; path: string; line: number }
export interface Patterns {
  idioms: Idiom[]; made: Made[]; pairs: PatternPair[]; entry_points: EntryPoint[]; layers: string[];
  hot_symbols: HotSymbol[]; hot_files: HotFile[]; naming: Naming[]; test_folders: string[]; errors: Raised[];
  angular: AngularComponent[]; react: ReactComponent[];
}


// ---- Change impact (ADR-018)

export interface ImpactNode {
  symbol_id: number; qualified: string; kind: string; file_id: number; path: string; line: number; depth: number;
  certainty: Usage["certainty"]; via: number; via_line: number;
}
export interface Impact {
  symbol: CodeSymbol;
  nodes: ImpactNode[];
  layers: { layer: string; nodes: ImpactNode[] }[];
  routes: { route: string; handler: string; handler_id: number; depth: number }[];
  tests: { file_id: number; path: string; symbols: string[] }[];
  truncated: boolean;
  by_name_included: boolean;
}

// ---- Unused code (ADR-019)

export interface UnusedItem { symbol: CodeSymbol; certainty: "none" | "name"; by_name_references: number }
export interface UnusedReport {
  methods: UnusedItem[];
  by_name_only: UnusedItem[];
  routes: { route: string; handler: CodeSymbol | null; file_id: number; path: string; line: number }[];
  exports: UnusedItem[];
  types: UnusedItem[];
}

// ---- Snapshots and diffs (ADR-020)

export interface Snapshot { id: number; codebase_id: number; label: string; taken_at: string; symbol_count: number }
export interface IndexDiff {
  added: CodeSymbol[];
  removed: CodeSymbol[];
  changed: { now: CodeSymbol; before_signature: string; before_type: string; callers: Usage[] }[];
  moved: { now: CodeSymbol; before_path: string }[];
  removed_callers: Record<string, number>;
  removed_by_name_now: Record<string, number>;
  by_name_before: number;
  by_name_now: number;
  against: string;
}


// ---- Convention checks (ADR-021)

export interface Finding { kind: string; symbol: CodeSymbol; file_id: number; path: string; line: number; message: string; examples: Where[]; confidence: number }


// ---- Tables as data (ADR-022)

export interface TableAsCode {
  name: string; language: string; text: string; constants: string[]; columns: string[]; classes: string[];
  shape: "enum" | "layout"; fields: LayoutField[]; unit: string; total: number; notes: string[];   // ADR-030
}
export interface LayoutField { name: string; property: string; constant: string; offset: number; width: number; code: string }
export interface TypeComparison {
  type: CodeSymbol; matched: string[]; missing_in_code: string[]; extra_in_code: string[];
  extra: { name: string; symbol_id: number; line: number }[];
  differences: { field: string; what: string; table: number; code: number }[]; not_stated: string[]; by_name_only: boolean;
}
export interface EnumComparison {
  enum: CodeSymbol; matched: string[]; missing_in_code: string[]; extra_in_code: string[];
  extra: { name: string; symbol_id: number; line: number }[]; value_mismatches: [string, string][];
}


// ---- Traceability as mentions (ADR-014)

export interface CodeMention { codebase_id: number; file_id: number; path: string; line: number; text: string; certainty: "exact" | "name"; symbol: string; changed: string }
export interface FileIdentifier { identifier: string; line: number; certainty: "exact" | "name"; text: string }

// ---- Git and rename (ADR-015)

export interface GitInfo { repository: boolean; branch: string; entries: { path: string; status: string; old_path: string }[]; reason: string }
export interface GitCommit { commit: string; author: string; date: string; message: string }
export interface BlameLine { line: number; commit: string; author: string; date: string; summary: string; text: string; uncommitted: boolean }
export interface GitShown { commit: string; author: string; date: string; message: string; files: { path: string; added: number; removed: number }[]; diff: string }
export interface RenameEdit { key: string; file_id: number; path: string; line: number; col: number; text: string; certainty: string; selected: boolean; symbol: string }
export interface RenameMention { key: string; file_id: number; path: string; line: number; col: number; text: string }
export interface RenamePreview {
  symbol: CodeSymbol; new_name: string; edits: RenameEdit[]; also: CodeSymbol[];
  file_rename: [string, string] | null;   // The file renamed with a public Java class, when it's named after it
  collision: CodeSymbol | null;           // An existing symbol the name would clash with: applying is refused
  mentions: RenameMention[];              // Strings containing the old name: listed, never edited
}
export interface RenameResult { files: CodeFile[]; skipped: { key: string; path: string; line: number; reason: string }[]; edits_applied: number; renamed_file: string | null }

// ---- Fixing a PDF's dead links (ADR-031)

export type LinkState = "ok" | "dead" | "wrong page" | "unresolved" | "external";
export interface ReportLink {
  id: number; page: number; rect: BBox; text: string; kind: "goto" | "named" | "uri" | "other"; target: string; state: LinkState;
  reference: string; proposed_page: number | null; proposed_point: [number, number] | null; page_size: [number, number];
}
export type BookmarkState = LinkState | "unchecked";
export interface ReportBookmark { id: number; level: number; title: string; page: number | null; state: BookmarkState; proposed_page: number | null; proposed_title: string | null }
export interface ReportUnbookmarked { page: number; title: string; level: number }
export interface ReportUnlinked { page: number; rect: BBox; reference: string; target_page: number }
export interface LinkReport {
  token: string; filename: string; page_count: number; refused: string;
  links: ReportLink[]; bookmarks: ReportBookmark[]; unbookmarked: ReportUnbookmarked[]; unlinked: ReportUnlinked[]; counts: Partial<Record<LinkState, number>>;
}
