# ADR-002: Local only, no LLM, models of known provenance

**Status:** accepted (in force since the project began; the meaning-search exception dates from 2026-09-24)

## Context

The documents are licensed and distribution-restricted, and the tool is used on one machine. Nothing
about them may leave that machine, and nothing the tool reports may be invented.

## Decision

- The app runs entirely on the user's machine and needs the internet once, to install packages and
  download the embedding model. After that it must work with no connection (`HF_HUB_OFFLINE` is set
  once the model is present).
- **No large language model**, local or remote, and nothing generative: every result is a real
  passage, row or line from the user's own material. This is not a coding agent either (ADR-001).
- **Meaning search is allowed**, with a local embedding model, only when the model is made by
  Microsoft or Google, never by a Chinese organisation, pinned to an exact published revision, and run
  with sentence-transformers and PyTorch (no ONNX runtime). Third-party re-rankers don't qualify.
  The current model is `intfloat/e5-base-v2`; a provenance question about its authors' affiliation
  was raised with the user and is theirs to settle.
- The model only decides *that* two passages are about the same thing. *How* they differ (values,
  shall/should/may, negation, identifiers) is decided by fixed rules, so every finding can be explained.
- Telemetry of every kind is off, including in the libraries used.

## Consequences

- Features that need generation (summaries, answers, rewritten snippets) are out of scope for good.
- A model change re-embeds every document; the model is a setting in `src/config.py`, and documents
  record which model made their vectors.
- Anything proposed later that sends data anywhere, or that learns in a way nobody can explain,
  contradicts this record and needs a superseding one.
