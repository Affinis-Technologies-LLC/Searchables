# ADR-017: Java library symbols from class files

**Status:** accepted 2026-10-11 (agreed as part of the roadmap; the record for step 6, written
before building it).

## Context

The linker resolves what the codebase declares. Everything else in Java — `List`, `Optional`,
`Stream`, `PrintStream`, Spring, Jackson — is an outside API known only by name, so
`users.stream().filter(…)` resolves through a hand-written table of carrier types (ADR-010's
`_CARRIERS`), `System.out.println` stays by name, and completion on a library type lists only what
the codebase happens to have used. A compiler isn't allowed (ADR-001), and neither is running one
(ADR-011): but the libraries are on disk, as class files in jars, and a class file's public API
(name, supertypes, fields and methods with their descriptors and generic signatures) is a small,
stable binary format that can be read without a JVM.

## Decision

- **Sources, read where they are, never run:** the jars of the dependencies a build declares
  (`pom.xml`, `build.gradle`: `group:artifact:version`) found in the local Maven repository
  (`~/.m2/repository`) and Gradle cache (`~/.gradle/caches/modules-2/files-2.1`); and the JDK's own
  classes from `jmods/java.base.jmod` (JDK 9+) of a JDK found through `JAVA_HOME`, `SEARCHABLES_JAVA_HOME`,
  or the usual install folders on macOS, Linux and Windows. No download; a jar that isn't there
  stays by name. Reading `java.base` gives `java.lang`, `java.util`, `java.io`, `java.time`,
  `java.util.stream`, `java.util.function` and the rest of the platform's core.
- **What's read:** per class, its qualified name, kind, access, supertypes, type parameters; per
  public or protected member, its name, kind, parameter count, erased return/field type, and from
  the `Signature` attribute whether it returns a type variable (`Optional<T>.orElse` returns `T`) or
  carries one (`List<E>.stream()` returns `Stream<E>`). Nothing else (no bytecode, no private
  members, no annotations).
- **Storage:** a jar is read once into `code_jars` (path, size, mtime) and `code_library`
  (its classes and members), shared by every codebase that declares it; `code_codebase_jars`
  says which jars a codebase sees. A rescan re-reads a jar only when it changed.
- **The linker uses the library as a second layer under the codebase:** a simple type name not
  declared in the codebase resolves through single imports, wildcard imports and `java.lang` to a
  library class; a member on a library type resolves to its declaring class (`ArrayList#stream` →
  `java.util.Collection#stream`) with its return type, so chains continue through library calls
  and the hand-written carrier table is used only when no library is present. Targets stay strings
  (`java.util.Optional#orElse`): library symbols aren't symbols of the codebase, so usages,
  hotspots and patterns don't change meaning.
- **Completion on a library type** lists its public members (and inherited ones) with the number
  of examples in the codebase.
- **Measure:** the by-name share of Java calls (`python -m src.evaluate_code`) on the fixtures
  before and after, and on the real Java codebase when named; the JDK-dependent tests skip where no
  JDK is found and say so.

## As built

- `src/code/classfiles.py`: the reader (constant pool, access, supertypes, `Signature` attributes for
  type parameters and the first type variable), `read_archive` for jars and jmods, `jdk_home()`
  (`SEARCHABLES_JAVA_HOME`, `JAVA_HOME`, then the usual folders; newest wins), `find_jar()`
  (`SEARCHABLES_MAVEN_REPO`, `SEARCHABLES_GRADLE_CACHE`). `java.base` plus `java.sql`,
  `java.net.http`, `java.logging`, `java.xml` are read: 3,636 public classes from java.base in
  1.2 s; overloads of the same arity are stored once.
- Tables `code_jars`, `code_library`, `code_codebase_jars`; read at scan time after the manifests,
  re-read only when an archive's size or mtime changed, cached per process as well.
- The linker: `_load_libraries`, `_lib_member` (walks supertypes), `_outside_member` (names the
  declaring class), library-backed `_java_type` for wildcard imports and `java.lang`, and
  `_carrier_step` using the member's return type and type variable before the hand-written table.
- Completion on a library receiver lists its members with example counts (`kind: "api"`).
- Measure on `tests/codebase`: Java calls by name 4 of 16 without a JDK, 3 of 16 with one
  (`println` through `System.out`; what's left is an untyped lambda parameter and an unknown
  receiver). `stream` is now named `java.util.Collection#stream`, the class that declares it.
- Tests: `tests/test_library_symbols.py` (the JDK-dependent ones skip, saying so, where none is found).
  `SEARCHABLES_LIBRARIES=0` switches library reading off; the test suite sets it except in those tests.

## Options considered

- **Running `javap` or a compiler.** Not allowed (nothing is run).
- **Hand-written tables per library.** What exists today for carriers; doesn't scale past a dozen
  types and is wrong about overloads.
- **Reading `lib/ct.sym`** (signature stubs for every release, JDK 9+). Possible; jmods are simpler
  and present in every full JDK. ct.sym can follow if JDK installs without jmods turn out common.
- **Source jars.** Would need the parser and give no more than class files do for resolution.

## Consequences

- `src/code/classfiles.py` (the reader), three tables, the linker's second layer, completion's use
  of it; the JDK lookup as configuration (`SEARCHABLES_JAVA_HOME`).
- Reading `java.base` (about 6,000 classes) takes a few seconds once per machine.
- Windows service: the service account must be able to read the user's Maven/Gradle caches and the
  JDK; the README says so.
