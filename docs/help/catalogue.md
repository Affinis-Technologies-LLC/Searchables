# Catalogue

Every identifier found in the documents as an entry: messages, their words and fields, data items,
part numbers — whatever the documents define by a label. The families of identifiers (their
shapes, such as `M3.2` or `GRP/ITM 281/001`) are discovered in each document; the
[Library](library.md) view shows them and lets you switch a family off if it's noise.

## An entry

- **Where it's defined**: the passage that introduces it (a filled dot marks a heading or caption).
- **Its parts**: identifiers that extend it, and the tables it owns.
- **What uses it**: every passage and table row that mentions it.
- **Rules**: the provisions (*shall*, *should*, *may*) about it, each with **Copy**.

## Filtering

Type part of an identifier (`M3.2`, `GRP 281…`). `#` stands for any digit, so `M3.#` lists the
whole series. The **Pattern** box takes a family's shape.

## In the code

With a codebase in the Code view, an entry lists where the identifier's text appears in the code
(a string, a comment) and symbols named after it (`M3_2`, marked *by name*). These are mentions,
not a claim that the code implements the identifier. The other way round, a source file's
**File** view in the code inspector lists the identifiers it mentions.

## Changes between editions

With two editions of a document in the library, an entry shows what changed between them: rows of
its own tables added, removed or changed, and rules that exist in only one of the two. The
[Compare](compare.md) view shows the same from the document's side.
