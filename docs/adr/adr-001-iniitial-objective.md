# ADR-001: A code assistant without AI, built into Searchables

**Status:** accepted 2026-10-11 (refined from the initial brainstorm, which targeted an IntelliJ plugin).
Scope: all three layers. Java, JavaScript and TypeScript matter equally, and **Angular and React code
are first-class**. Not a coding agent: no LLM, nothing generated (ADR-002).

## Context

Searchables already indexes a codebase the way a research tool indexes documents: symbols,
references with their receivers and argument counts, imports, inheritance, HTTP endpoints, and a
browser with go-to-definition, usages, call trees and dependency views. Its linker follows imports,
declared types and scope; what it can't tell without compiling is kept "by name".

The objective is **engineering productivity, in coding and in standards discovery**, without AI:
a **coding assistant** that, as a developer types, selects real snippets from the codebase that show
how the thing they are writing is done elsewhere, and lets them explore and discover the patterns of
a codebase they don't know; and the same discovery for the standards the code implements. The earlier draft
planned this as an IntelliJ plugin on top of IntelliJ's PSI and type resolution. This ADR moves it
into Searchables instead, extending the Code view into a web-based editor, **without debugging or
compilation**.

Two things make this tool a better home than a plugin:

- **It already knows the documents.** A codebase that implements a standard can be traced both ways:
  from an identifier in the Catalogue to the code that handles it, and from a line of code to the
  rule it implements. No IDE does this.
- **It is built for discovery, not just editing.** Usages, call trees, dependency maps, endpoint
  matching and the research trail already exist; examples and patterns are a natural extension.

One thing makes it harder: **we don't have a compiler.** IntelliJ resolves every expression's type.
Our linker resolves declared types, imports and inheritance, and leaves chained calls, inferred
locals and most of dynamic JavaScript unresolved. The assistant's precision is bounded by this, so
improving resolution is part of the plan, not an afterthought. "More powerful than IntelliJ" is a
fair goal for *context* (what the developer sees around a piece of code) and *discovery*; it is not a
fair goal for type-level precision, and the design shouldn't pretend otherwise.

## Decision

Build the assistant as three layers on the existing code index, in this order.

### 1. Resolution good enough to rank on types

Extend the linker (`src/code/store.py`) so that most expressions a developer types have a known type,
in Java and in TypeScript and JavaScript alike:

- **Return types.** Signatures are stored as text; parse the return type of methods and functions and
  record it. Then `a.b().c()` resolves: `b()`'s return type gives the receiver of `c()`.
- **Field and local types across files.** A field's declared type already resolves; follow it into
  the owning type's members for calls through fields of fields.
- **Inferred locals.** `var x = repo.find()` and `const x = api.get()` take the return type of the call.
- **Constructor and factory results.** `new X()` and `X.of()` give `X`.
- **TypeScript annotations.** Parameter and return annotations already parse; use them the same way,
  including constructor parameter properties (`constructor(private users: UserService)`), so
  `this.users.list()` links.
- **Framework conventions, as rules in the parser and linker** (not in the UI):
  - *Angular:* class decorators (`@Component`, `@Injectable`, `@NgModule`, `@Directive`, `@Pipe`) and
    member decorators (`@Input`, `@Output`, `@ViewChild`) recorded as what they are; constructor
    injection as typed fields; **templates read as code**: the `templateUrl` file and inline
    `template`, where a component's selector is a reference to the component, and bindings such as
    `(click)="choose(user)"` and `{{ user.name }}` are references to its members; `@Input`/`@Output`
    bindings link to the child component's fields; modules' `declarations`/`imports`/`providers` link.
  - *React:* function and class components; hooks (`useX`, custom hooks) and their calls; props
    types; JSX elements already link, and wrapped default exports (`export default React.memo(X)`,
    `connect(...)(X)`, `forwardRef(X)`) must alias `X`; context providers and consumers.
  - *RxJS and promises:* `subscribe`, `pipe`, `then` chains carry the type of what they're called on,
    so the call they wrap still links.
- **A TypeScript language service is not assumed.** It would give full TypeScript resolution at the
  cost of Node.js on the target machine; the decision is deferred until the rules above have been
  measured on real Angular and React code. The index design must not preclude adding one.

Measured by the existing by-name share: the fraction of calls left unlinked, per language, before
and after, on real Angular, React and Java codebases. (Today it's about 2% on the synthetic Java
corpus and far higher on real JavaScript.) `tests/test_web_frameworks.py` lists the known gaps as
strict expected failures and is the first thing this layer makes pass.

### 2. The assistant: context → candidates → ranked examples

**Context capture** happens on the unsaved buffer, in the browser's editor, on every pause in typing:
the file, cursor, and the text as it is now. The server parses the buffer with tree-sitter (the same
parser as the index) and works out:

- the enclosing symbol, type and package;
- the expression under construction: receiver (`userRepository.`), its resolved type, the partial
  member name, the arguments so far;
- the surrounding statements: what else the enclosing method calls, what it declares, what it returns;
- the imports in the file.

**Candidate selection** is a hard filter before any ranking, so an incompatible example never
outranks a valid one:

- calls on the same resolved type (or its supertypes), when the receiver resolves;
- else members of that name on any type, flagged as by-name;
- never the line being written.

**Ranking** is deterministic, with the draft's weighted score kept as the starting point:

| Feature | Weight | How it's computed |
|---|---|---|
| Type compatibility `T` | 0.30 | Same receiver type 1.0; supertype 0.8; same name on another type 0.3 |
| Symbol similarity `M` | 0.25 | Same member 1.0; same member on a sibling type 0.7; overload 0.5 |
| Context similarity `C` | 0.20 | Jaccard overlap between the calls, types and identifiers in the two enclosing methods |
| Structural similarity `P` | 0.15 | Similarity of the statement-kind sequence around the call (tree-sitter node kinds) |
| Example quality `Q` | 0.10 | Short, complete statement; not generated or vendored; test code counts as good, not bad |

Weights are configuration, and the developer's choices (previewed, navigated, inserted, dismissed)
are recorded locally so the weights can be tuned by hand against them. No learning in the loop.

**Presentation**, in the editor:

- an **Examples** panel beside the editor, updating as you type, each example with its file and
  lines, the score and *why* it was chosen ("same repository type, called from a service like this
  one"), and **Preview · Go · Insert**;
- **completion** from the index, not from text: members of the resolved receiver type, symbols in
  scope, importable symbols, with the example count beside each;
- the inspector keeps showing usages, calls and hierarchy for whatever the cursor is on.

### 3. Discovery: patterns of an unfamiliar codebase

Mined from the index and the parsed bodies, shown as a **Patterns** view with examples for each:

- **Idioms per type:** what is usually called on a `Repository`, in what order (frequent call
  sequences within a method, mined with a simple sequential pattern count over method bodies);
- **How things are made:** the usual way a type is constructed or obtained (constructor, factory,
  injection);
- **Pairs that go together:** calls that almost always appear in the same method (`begin`/`commit`,
  `lock`/`unlock`, `open`/`close`);
- **Entry points and layers:** endpoints → handlers → services → repositories, from the call graph and
  the package dependency map;
- **Hotspots:** the most-used symbols and the files most referenced;
- **Conventions:** naming (prefixes and suffixes by kind), where tests live, how errors are raised;
- **Traceability to documents:** identifiers from the Catalogue found as strings or names in the code,
  and the rules they implement, with the code that reads or writes them; the same from a document's
  side: for a rule, the code that implements it.
- **Framework views:** for Angular, components with their selectors, templates, inputs and outputs,
  and the services injected where; for React, the component tree from JSX, the hooks each uses, and
  the props that flow down.

### The editor (what "web-based IDE" means here)

The Code view's editor becomes writable, with what an editor needs and nothing that needs a compiler:

- edit and **save** (atomic write; refuses to overwrite a file changed on disk since it was opened);
- new, rename, move and delete files, project-wide find and replace;
- go to definition, usages, call trees and hierarchy as now; **rename symbol** with a preview of every
  linked and by-name reference, applied only to the ones confirmed;
- **git**: status, diff and commit through the `git` command (no push by default);
- the index updated on save: the file re-parsed and **re-linked incrementally** (the file's own
  references, and references elsewhere to its symbols), instead of the whole codebase.

Out of scope, by decision: debugging, compilation, running builds or tests, and a language server.
Formatting is out until a formatter that needs no runtime is chosen.

## Options considered

- **IntelliJ plugin (the draft).** Best type resolution, worst fit: a second codebase in Kotlin, no
  link to the documents, no discovery views, and the assistant's value tied to one IDE.
- **A language server inside Searchables.** Would close the resolution gap for Java (Eclipse JDT) and
  TypeScript (tsserver), at the cost of Java and Node runtimes on the target machine. Deferred; the
  index design doesn't preclude it, and the resolution work in layer 1 is still needed to rank.
- **Text search with better ranking (BM25 over code).** Cheap, already available, and the baseline
  the assistant must beat. Kept as the fallback when nothing resolves.
- **An LLM, or a coding agent.** Ruled out: nothing is generated, and the tool suggests code it has
  found, never code it has written (ADR-002).

## Consequences

- The server gains write access to the codebase folder. Saves are atomic and checked against the
  file's hash; the folder stays the only thing written. Running arbitrary commands is not added.
- The index must update incrementally on every save; today a rescan re-links everything.
- Ranking quality is unmeasured until there is an evaluation set: recorded typing contexts with the
  examples a developer judged useful, in the same spirit as `src/evaluate.py` for documents.
- JavaScript precision stays lower than Java's; the UI must keep saying which links are by name.

## Plan

Before any of it: the tests that protect what exists (ADR-008) stay green, and every step adds its
own tests first, on made-up code, with the gaps it is to close marked as strict expected failures.

1. **Resolution** (layer 1), with the by-name share as the measure, on Java, Angular and React alike.
2. **Incremental re-link on save**, and the writable editor with save, files and project search.
3. **Examples panel and index completion**, with the scoring model and local feedback recording.
4. **Patterns view**, starting with idioms per type and call pairs.
5. **Traceability** between Catalogue identifiers and code.
6. **Git status, diff and commit; rename symbol.**

## Open questions

- At what measured by-name share on real Angular and React code does a TypeScript language service
  become worth Node.js on the target machine?
- Should examples be adapted on insert (renaming variables to the ones in scope), or inserted as-is?
  As-is first; adaptation needs type information the index may not have.
- Which codebases will be used to build the evaluation set (one Java, one Angular, one React), and
  who judges the examples?
