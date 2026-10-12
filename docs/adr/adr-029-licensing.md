# ADR-029: Licensing

**Status:** accepted 2026-10-12. A record, not a build: it states the licence
of the project's own code, what the bundled software imposes, and what would reopen the question.
Not legal advice; the one point marked below is where a lawyer's confirmation would be sought.

## Context

The project's own code had no licence file until 2026-10-12, when `LICENSE` (MIT, Affinis
Technologies LLC) was added. The releases (ADR-028) bundle everything the app runs on, so what
reaches another machine is the project's code plus about fifty third-party components. Their
licences, from the bundle's own `LICENCES.md`: MIT, BSD, Apache-2.0, PSF and MPL throughout —
permissive — with **one exception: PyMuPDF**, dual-licensed "GNU AGPL 3.0 or Artifex commercial
licence". PyMuPDF reads the PDFs (`src/extractor/pdf.py`: text, page images, the OCR path); the
app has no PDF reading without it. The E5 model is MIT; WinSW and the Python build are MIT and
PSF/MPL.

The owner has said the project will not be distributed publicly for profit, since it is largely
built on open source.

## Decision

- **The project's own code is MIT** (`LICENSE`), chosen deliberately over AGPL: it is the most
  open terms for a project built on open source, it is compatible with every bundled licence, and
  it leaves the code free to reuse without copyleft — by the owner in other work, or by anyone
  who replaces PyMuPDF. Switching the project to AGPL would add obligations on the owner's own
  code and remove none of PyMuPDF's.
- **What governs a distributed copy is the AGPL**, because PyMuPDF is in it: whoever receives a
  release, or uses the app over a network, must be able to obtain the complete source. That is
  met by the public repository at the tagged commit the release's `RELEASE.md` names; every
  release is built from a tag of this repository and nothing else.
- **Releases are given, not sold**, and the source is public. On those two facts no further
  obligation arises from any bundled component, and none from internal use.
- **Every release states this**: `LICENCES.md` lists each bundled component's licence (PyMuPDF
  marked as AGPL/commercial), About in the app says the project is MIT and names PyMuPDF's AGPL,
  and the README's licence note says the same in one paragraph.
- **What would reopen the question**, and the two answers if it does: selling the app, or hosting
  it for people outside the organisation. Then either (a) a commercial PyMuPDF licence from
  Artifex, which removes the source obligation for the whole program, or (b) replacing PyMuPDF
  with a permissively licensed reader — a contained change to `src/extractor/pdf.py` judged by
  the extraction tests (ADR-003), but real work, since it is the part that reads the standards.
  Neither is done now.
- **The point to confirm with a lawyer**, should either trigger come near: whether use by one
  organisation's own staff over its network counts as "users interacting with the program" under
  AGPL §13. The common reading, and the FSF's, is that internal use does not; this record does not
  rely on it, since the source is public anyway.

## Measures

- `LICENSE` exists and is MIT; the build script copies it into every release and `LICENCES.md`
  points to it (already the case: `deploy/build-release.py`).
- `tests/test_release.py` gains one assertion: the licence table of a built bundle names PyMuPDF
  with its AGPL/commercial terms, so a dependency change that dropped or hid it would be noticed.
- No code changes; no re-upload of 1.4.0 (its archives predate `LICENSE`; the repository carries
  it, and 1.5.0 will bundle it).

## Consequences

- The README's licence note, About's line and this record say one thing. The ADR index gains the
  row; the roadmap lists no step, since nothing is built.
- Contributions from outside the owner would make a later relicensing of the project's own code
  need each contributor's agreement; if contributions are expected, a one-line contributor note
  (MIT in, MIT out) in `AGENTS.md` is the moment to add it.

## As recorded

- `tests/test_release.py::test_pymupdf_s_agpl_terms_are_named_in_the_licence_table`: in the
  running environment and in every bundle built under `dist/build`, the licence table names
  PyMuPDF with its "GNU AFFERO GPL 3.0 or Artifex Commercial License" terms, and no other
  component's licence is GPL-family (LGPL excepted) — a new copyleft dependency fails the test and
  reopens this record. It passed against this environment and the three 1.4.0 bundles.
