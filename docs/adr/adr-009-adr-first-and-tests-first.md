# ADR-009: Decide in writing before building; protect with tests before changing

**Status:** accepted 2026-10-11

## Context

The codebase is worked on by people and by coding agents, in large steps. Both need the same
account of why the code is the way it is, and the same gate before changing it. Without that,
an agent departs from decisions it never saw, and a person can't tell a deliberate design from
an accident.

## Decision

1. **An ADR comes before anything new.** New behaviour, a new component, a new dependency, or a
   change to a recorded decision starts with a record in `docs/adr/`: the context, the decision,
   the options considered, the consequences, and how success is measured. The record is agreed
   (by the person) before building starts. Small fixes within a recorded decision need no record.
2. **Tests come before the change.** Before behaviour is changed, tests protect what exists; the
   gaps a change is to close are written first as strict expected failures (`xfail(strict=True)`),
   so the suite itself says what is done and what is not. A change in behaviour ships with a test
   that would have caught the old behaviour.
3. **Records are never rewritten to mean something else.** A later record supersedes an earlier
   one and says which; the index in `docs/adr/README.md` lists every record.
4. **The roadmap names the record each step needs** (`docs/roadmap.md`): a step with no record is
   not ready to build.
5. **Agents follow `AGENTS.md`**, which points at the records, the conventions and the gates; it is
   kept short and current. Anything an agent learns that a future agent needs goes into a record
   or into `AGENTS.md`, not into a chat.

## Consequences

- Work slows at the start of each step and speeds up after: the design is on file, and tests say
  when a step is finished.
- A proposal that can't be written as a record (no measure of success, no options considered)
  isn't ready.
- Reviewing a change means reading its record and its tests before its code.
