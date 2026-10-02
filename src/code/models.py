from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class Codebase:
    id: int
    name: str
    root: str                   # The folder it's read from; files are indexed where they are
    added_at: str
    indexed_at: str = ""        # "" until the first scan finishes
    file_count: int = 0
    symbol_count: int = 0


@dataclass(frozen=True)
class CodeFile:
    id: int
    codebase_id: int
    path: str                   # Relative to the codebase root, with forward slashes
    language: str               # java, javascript or typescript
    package: str                # Java package; for JS/TS the file's folder
    lines: int
    has_errors: bool            # Parsed with syntax errors: some of its symbols may be missing


@dataclass(frozen=True)
class Symbol:
    id: int
    codebase_id: int
    file_id: int
    parent_id: Optional[int]
    kind: str                   # class, interface, enum, record, annotation, type, method, constructor, field, function, variable
    name: str
    qualified: str              # "com.acme.UserService#find"; for JS/TS "UserService#find" within its file
    line: int
    end_line: int
    signature: str
    params: int
    exported: bool
    path: str                   # Its file
    language: str

    @property
    def is_type(self) -> bool:
        return self.kind in ("class", "interface", "enum", "record", "annotation", "type")

    @property
    def is_callable(self) -> bool:
        return self.kind in ("method", "constructor", "function")

    @property
    def location(self) -> str:
        return f"{self.path}:{self.line}"


# How sure a link from a reference to a symbol is
RESOLVED = "resolved"       # Followed through imports, declared types or scope
SUPERTYPE = "supertype"     # A call through a supertype's method that this one overrides or implements
BY_NAME = "name"            # Only the name (and argument count) agree: what it's called on couldn't be told


@dataclass(frozen=True)
class Usage:
    """A place a symbol (or an external API) is referred to."""
    ref_id: int
    kind: str                   # call, new, extends, implements, type, annotation, jsx, use
    name: str
    line: int
    col: int
    file_id: int
    path: str
    text: str                   # The source line
    from_symbol: Optional[int]  # The symbol it's in
    from_name: str
    certainty: str = RESOLVED
    target_id: Optional[int] = None
    target: str = ""            # External target: "java.util.List#add", "axios#get"


@dataclass(frozen=True)
class Dependency:
    """A library declared in a build file (pom.xml, build.gradle, package.json)."""
    manifest: str
    ecosystem: str              # maven, gradle or npm
    name: str                   # "group:artifact" or the npm package name
    version: str
    scope: str                  # compile, test, dev…
    used_in: Optional[int] = None   # npm: files importing it (None where imports can't be tied to a library)


@dataclass(frozen=True)
class Endpoint:
    id: int
    side: str                   # server or client
    method: str
    path: str
    line: int
    file_id: int
    file_path: str
    symbol_id: Optional[int]
    symbol_name: str
    framework: str


@dataclass(frozen=True)
class CallNode:
    """One step of a caller or callee tree."""
    symbol: Symbol
    line: int                   # Where the call is made (in the caller)
    children: Tuple["CallNode", ...] = ()
    truncated: bool = False     # Deeper calls exist but weren't followed (depth limit, or already shown above)


@dataclass(frozen=True)
class Hierarchy:
    supertypes: List[Symbol]
    external_supertypes: List[str]
    subtypes: List[Symbol]
    overrides: List[Symbol]         # Methods this one overrides or implements
    overridden_by: List[Symbol]
