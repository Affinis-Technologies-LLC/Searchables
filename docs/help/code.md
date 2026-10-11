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
- **Git**: the branch, the files changed on disk, the diff of each, and **Commit** with a message.
  This is the one program the app starts, and only for status, diff, log and commit: it never
  pushes, pulls or changes the working tree.
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
  certainty; only the places you tick change. Methods that override one another are renamed
  together.
- `F12` or `Ctrl`+click goes to a declaration; `Shift`+`F12` finds usages; hovering a name says
  what it refers to.
- The inspector on the right follows the cursor: **Usages**, **Calls** (callers and callees as
  trees), **Impact** (everything that reaches the symbol through calls, by layer, with the routes
  and tests among them: what could break if you change it), **Hierarchy**, **Members**, the
  **File**'s outline.
- Every link carries its certainty: **Linked** (followed through imports, types or scope),
  **through a supertype**, or **by name only** (the name and argument count agree but what it's
  called on couldn't be told). Check by-name links before relying on them.

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
