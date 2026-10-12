# Code

Browse a codebase the way an IDE does, edit it, and get examples from it while you type. Java,
JavaScript and TypeScript, including Angular and React code and Angular templates.

## Adding a codebase

Give the top folder of the source on this machine. It's read where it is, in the background;
**Rescan** reads new and changed files again. Nothing in the folder is written except the files
you save here.

For Java, the index also reads the public API of the JDK and of the libraries the build declares
(from the class files already on this machine, with nothing run or downloaded), so calls through
library types resolve and completion lists their members.

## Finding things

- **Search**: symbols (classes, methods, functions, fields) by name, or any text in the source.
  **Replace** in the text search changes a string across the codebase after a preview.
- **Files**: the file tree; **+** creates a file, **Rename** moves the open one, the trash deletes it.
- **Dependencies**: libraries declared in the build files and whether they're used, the outside
  packages imported and where, and which package depends on which.
- **APIs**: the HTTP routes the code serves, with the calls that reach them.
- **Unused**: methods nothing calls, routes nothing reaches, exports nothing imports, types nothing
  refers to. Routes, tests, entry points, lifecycle and annotated methods are never listed; symbols
  whose only references are by name are shown apart, as uncertain, not as dead.
- **Search → Signature**: symbols by what they take and return: methods taking a `User` and
  returning `Optional`, fields of a type, functions returning `Promise`.
- **Checks**: methods and types that break what this codebase usually does (a call without its
  usual companion, a name against the package's convention, a one-off exception, a handler unlike
  its siblings), each with the places that follow the rule. The same findings show in the editor as
  information markers. They're questions, not errors.
- **Git**: the branch, the files changed on disk, the diff of each, and **Commit** with a message;
  a recent commit opens with its files and the diff of a chosen one. This is the one program the
  app starts, and only for status, diff, log, blame, show and commit: it never pushes, pulls or
  changes the working tree.
- **Blame** (a button on the code tab) adds a column beside the editor: who last changed each line
  and when, from git; a run of lines from one commit shows it once; lines not committed yet say
  so. Blame is of the file on disk, so it says "on disk" while the tab has unsaved changes. A click
  on a line opens that commit in the inspector's **History**.
- **History** in the inspector: the commits that changed the chosen symbol's lines (a method's or
  class's own history), or the whole file with renames followed; one opens with its message, files
  and the diff for this file. In the Catalogue, an identifier's **In the code** mentions carry the
  date their line last changed. All read from git; nothing is written.
- **Changes**: take a snapshot of the index, make a change, rescan, and compare: symbols added,
  removed, changed (with the callers affected) or moved. Two checkouts indexed as two codebases
  compare the same way.
- **Patterns**: what's usual in this codebase, counted from the index: what's called on each type
  and in what order, how types are obtained (injected, constructed, from a factory), calls that go
  together, entry points and the layers beneath them, the most-referenced symbols and files, naming
  conventions, where tests live, how errors are raised, and the Angular components and React
  component tree. Every row opens the places it was counted from.

## In the editor

- **Rename…** on a symbol in the inspector previews every place the name would change, with its
  certainty; only the places you tick change. What a rename covers: the declaration, every linked
  reference (calls, constructions, type uses, and reads and writes of a field such as `this.x`),
  template bindings, import lines (`import { X }` keeps an alias `as Y` as it is), and, for a Java
  class, its constructors and `new X()`; when a public Java class's file is named after it, the file
  is renamed too (ticked by default). Methods that override one another are renamed together.
  What it refuses: a reserved word, and a name that already exists on the type, its supertypes or
  subtypes, in the file, or in the Java package — the clash is named and nothing changes. Strings
  that contain the old name are listed as **mentioned in strings**, found by search and never
  changed; check them yourself.
- `F12` or `Ctrl`+click goes to a declaration; `Shift`+`F12` finds usages; hovering a name says
  what it refers to.
- The inspector on the right follows the cursor: **Usages**, **Calls** (callers and callees as
  trees), **Impact** (everything that reaches the symbol through calls, by layer, with the routes
  and tests among them: what could break if you change it), **Hierarchy**, **Members**, the
  **File**'s outline.
- Every link carries its certainty: **Linked** (followed through imports, types or scope, including
  type arguments bound through supertypes and the parameters of callbacks such as `forEach(o -> …)`),
  **through a supertype**, **by rule** (an outside API a framework provides without a declaration
  the index can read, such as a Spring Data repository's `findById`), or **by name only** (the name
  and argument count agree but what it's called on couldn't be told). Check by-name links before
  relying on them.
- Outside APIs are known from their declarations where those are on disk: Java class files in the
  JDK and the local Maven/Gradle caches, and the `.d.ts` files of the npm packages a `package.json`
  declares (in `node_modules`, with TypeScript's own `lib.*.d.ts` for the built-ins and the browser).
  Nothing is run and nothing is downloaded.

## Editing

- `Ctrl`/`Cmd`+`S` saves. The file is re-read and re-linked at once. Unsaved changes are marked
  **●** on the tab, survive switching tabs and reloading the page, and are asked about when you
  close the tab.
- If the file changed on disk since you opened it, the save is refused and nothing is written.
  **Compare** shows both versions; take the one on disk or keep yours.
- Line endings, byte-order marks and encodings are kept as they were.
- Only source, template and build files inside the codebase folder are ever written. Nothing is
  run: no build, no tests, no formatter.

## Examples as you type

After a pause in typing, the inspector's **Examples** view shows statements of this codebase that
do what you're writing: a call of the same method on the same type first, then on sibling types,
then the same name anywhere (marked **by name**), then code from methods like the one you're in.
Each example shows its file and lines, a score and the reason it was chosen.

- **Preview** shows the whole method it's in; **Go** opens it; **Insert** puts the statement at
  your cursor, as written; **Dismiss** hides it for this context.
- Completion (`Ctrl`+`Space`, or after a dot) comes from the index, never from the text of the
  file: the members of the type you're calling on, with the number of examples each has; what's in
  scope; then symbols you could import, which adds the import for you.

Nothing is generated. Every example is code that exists; what you do with them is recorded only
on this machine, to tune the ranking by hand.
