# Search

Searches every document in the library, or the ones you tick.

## Three ways to search

- **Words.** Type words, a question, or `"an exact phrase"`. Passages containing the words come
  first, ranked by how well they match.
- **Meaning.** Once a document has meaning search (see [Library](library.md)), passages that say
  the same thing in other words are found too, marked **meaning**. They don't contain all your
  words; read them with that in mind.
- **Identifier.** Tick **Identifier** to look one up exactly: a message label, a field, a part
  number. The results are grouped by role (where it's defined, where it's used, where it appears in
  a table) and list related identifiers. **Include extensions** also matches identifiers that extend
  the one you typed. Each one you follow joins a trail; **Back** returns along it.

## Narrowing

- **Provisions** keeps only passages of a kind: *shall* (requirements), *should*
  (recommendations), *may* (permissions), notes and examples. The kind is read from the verb, so
  it's reliable for text that follows the usual drafting style and approximate elsewhere.
- **Content** (text, tables, figures) and the documents ticked narrow further.
- **Relevance** orders by match; **Position** by document and page, for reading in order.

## Acronyms

When a document has an acronyms list, a search for an acronym also looks for its spelled-out form,
and the other way round. The expansion used is shown under the search box.

## Tables as code

In the inspector's **Tables** view, a table can be rendered **as a Java enum** or **as TypeScript**
(one constant per row, the other columns as its values), copied or inserted into the open source
file, and **compared with an enum** of a codebase: which rows the enum has, which it's missing, which
constants it has that the table doesn't, and values that differ.

## Results

A result shows the passage, its document, clause and page. **Open** shows it on the page, with the
matches highlighted; the inspector on the right then shows what it's related to, the page's tables,
references and defined terms. **Copy** copies the passage, with its citation when **Cite when
copying** is on. **CSV** saves the results.
