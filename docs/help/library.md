# Library

Where documents are added and kept indexed.

## Adding a document

Drop a PDF or choose it. It's read in the background: text, headings, tables, identifiers,
provisions, acronyms and the distribution statement. Scanned pages are read with OCR when it's
installed. The bottom bar shows progress; the document can be searched as soon as it's done.

## Meaning search

**Add meaning search** processes a document with the local language model, so [Search](search.md)
can find passages that say the same thing in other words. The model is downloaded once and then
used offline; it only compares text and never writes any. A document without it is still searched
by words and identifiers.

## Each document

- **Save title** renames it; **Re-index** reads the stored PDF again (after an update of the app
  that reads documents better; such documents are marked).
- **Health** reports how the document was read: pages with little text, clauses found, tables,
  identifier families, acronyms, the distribution statement. It's the place to look when a view
  seems empty for a document.
- **Identifier families** lists the shapes of identifiers discovered in it (`M3.#`, `GRP/ITM
  ###/###`). Switch one off if it's noise, or on if it was missed; **Reset all to automatic**
  returns to what was discovered.

## Where things are

The library (documents, index, pins, notes) is in the app's data folder, shown under **Account →
About**. Nothing is sent anywhere.
