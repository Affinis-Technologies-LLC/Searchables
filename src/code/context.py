"""
What's being written (ADR-012): the unsaved buffer at the cursor, parsed in memory with the same
parser as the index, and resolved with the codebase's linker state. Nothing here is stored.

The expression under construction is read from the text before the cursor ("repository.fi",
"repository.save(order, ", "new Ord", "fetchOr"); to resolve its receiver the member being typed is
replaced by a sentinel call and the buffer parsed, so the parser's own rules (locals, fields, chains,
casts, awaits) give the receiver chain, which the linker follows to a type.
"""
import hashlib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from src.code.models import Symbol
from src.code.parser import JAVA, TYPE_KINDS, ParsedFile, ParsedSymbol, parse
from src.code.store import CodeStore

SENTINEL = "__sx__"
_WORD = r"[A-Za-z_$][\w$]*"
_KEYWORDS = {"if", "for", "while", "return", "new", "else", "switch", "case", "throw", "try", "catch", "import",
             "export", "const", "let", "var", "await", "async", "function", "class", "public", "private", "protected",
             "static", "final", "void", "this", "super", "true", "false", "null", "undefined", "typeof", "instanceof",
             "do", "break", "continue", "default", "in", "of", "extends", "implements", "yield", "delete"}


@dataclass
class Expression:
    kind: str = "none"          # call, new, jsx, annotation, none
    name: str = ""              # The member or function named so far: the callee when the cursor is in its arguments
    partial: str = ""           # What's typed of the name when it isn't complete yet ("fi" in "repository.fi")
    receiver: str = ""          # As written ("repository", "this.users", "")
    args_so_far: int = -1       # In the arguments of a call: how many are begun
    chain: str = ""             # The receiver as a chain the linker follows (parser.ParsedRef.chain)
    start_col: int = 0          # Where the expression starts on the cursor's line (1-based)


@dataclass
class TypeRef:
    id: Optional[int]           # A type of the codebase, or None for an outside one
    qualified: str
    path: str = ""
    certainty: str = "resolved"  # resolved, or "by name" when nothing could be followed
    carried: str = ""           # For carriers (Optional<Order>): what they carry


@dataclass
class Neighbours:
    calls: Set[str] = field(default_factory=set)
    types: Set[str] = field(default_factory=set)
    identifiers: Set[str] = field(default_factory=set)
    shape: str = ""             # Statement kinds around the cursor (parser.statement_shape)

    def names(self) -> Set[str]:
        return self.calls | self.types


@dataclass
class Enclosing:
    id: Optional[int]           # The stored symbol, when the buffer's one is in the index
    kind: str
    qualified: str
    name: str
    type: str
    package: str
    line: int
    end_line: int
    type_id: Optional[int]      # The stored enclosing type (for `this`)


@dataclass
class Context:
    file_id: int
    codebase_id: int
    language: str
    path: str
    line: int
    col: int
    expression: Expression
    enclosing: Optional[Enclosing]
    receiver_type: Optional[TypeRef]
    neighbours: Neighbours
    imports: List[str]
    locals: Dict[str, str]      # Names in scope in the enclosing method → declared type or chain
    parsed: ParsedFile
    enclosing_index: Optional[int]
    digest: str


# ---- Reading the expression under construction ----------------------------------------------------

def _receiver_start(prefix: str, end: int) -> int:
    """Walks back over a receiver expression ending at `end` (just before a dot): names, calls, indexes, dots."""
    i = end
    while i > 0:
        c = prefix[i - 1]
        if c in ")]":
            depth, open_char = 0, "(" if c == ")" else "["
            while i > 0:
                i -= 1
                if prefix[i] == c:
                    depth += 1
                elif prefix[i] == open_char:
                    depth -= 1
                    if depth == 0:
                        break
            continue
        if c.isalnum() or c in "_$.":
            i -= 1
            continue
        if c == ">" and "<" in prefix[:i]:   # A generic call: list.<T>of()  (rare; stop)
            break
        break
    while i < end and prefix[i] == ".":
        i += 1
    return i


def _unclosed_call(prefix: str) -> Optional[int]:
    """Index of the last "(" not closed before the cursor, outside strings; None when every call is closed."""
    depth, quote = 0, ""
    unclosed = []
    for i, c in enumerate(prefix):
        if quote:
            if c == quote and prefix[i - 1] != "\\":
                quote = ""
            continue
        if c in "\"'`":
            quote = c
        elif c == "(":
            unclosed.append(i)
        elif c == ")":
            if unclosed:
                unclosed.pop()
        elif c in "{};":
            unclosed.clear()
    return unclosed[-1] if unclosed else None


def _args_so_far(text: str) -> int:
    depth, count, quote, content = 0, 0, "", False
    for i, c in enumerate(text):
        if quote:
            if c == quote and text[i - 1] != "\\":
                quote = ""
            continue
        if c in "\"'`":
            quote = c
            content = True
        elif c in "([{":
            depth += 1
            content = True
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            count += 1
            content = False
        elif not c.isspace():
            content = True
    return count + 1   # The argument being written counts


def read_expression(prefix: str, language: str) -> Expression:
    """The expression under construction, from the text before the cursor on its line."""
    stripped = prefix.rstrip()
    # Inside the arguments of a call: the callee is named, the receiver is before it
    paren = _unclosed_call(prefix)
    if paren is not None:
        before = prefix[:paren].rstrip()
        match = re.search(rf"({_WORD})$", before)
        if match and match.group(1) not in _KEYWORDS - {"super", "this"}:
            name = match.group(1)
            head = before[:match.start(1)]
            kind = "call"
            receiver = ""
            if head.endswith("."):
                start = _receiver_start(head, len(head) - 1)
                receiver = head[start:len(head) - 1]
            elif re.search(r"\bnew\s+$", head):
                kind = "new"
                start = len(head) - len(re.search(r"new\s+$", head).group(0))
            else:
                start = match.start(1)
            return Expression(kind, name, "", receiver, _args_so_far(prefix[paren + 1:]), start_col=start + 1)
    # A member being typed after a dot
    match = re.search(rf"\.((?:{_WORD})?)$", prefix)
    if match:
        start = _receiver_start(prefix, match.start())
        return Expression("call", "", match.group(1), prefix[start:match.start()], start_col=start + 1)
    match = re.search(rf"\bnew\s+((?:{_WORD})?)$", prefix)
    if match:
        return Expression("new", "", match.group(1), start_col=match.start() + 1)
    if language != JAVA:
        match = re.search(rf"<((?:{_WORD})?)$", prefix)
        if match:
            return Expression("jsx", "", match.group(1), start_col=match.start() + 1)
    match = re.search(rf"@((?:{_WORD})?)$", prefix)
    if match:
        return Expression("annotation", "", match.group(1), start_col=match.start() + 1)
    match = re.search(rf"(?<![\w$.])({_WORD})$", prefix)
    if match and match.group(1) not in _KEYWORDS:
        return Expression("call", "", match.group(1), "", start_col=match.start(1) + 1)
    return Expression("none", start_col=len(stripped) + 1)


# ---- The context ------------------------------------------------------------------------------------

def _enclosing_index(parsed: ParsedFile, line: int) -> Optional[int]:
    """The deepest symbol whose lines hold the cursor."""
    best = None
    for index, symbol in enumerate(parsed.symbols):
        if symbol.line <= line <= symbol.end_line and (best is None or symbol.line >= parsed.symbols[best].line):
            best = index
    return best


def _enclosing_type_index(parsed: ParsedFile, index: Optional[int]) -> Optional[int]:
    while index is not None and parsed.symbols[index].kind not in TYPE_KINDS:
        index = parsed.symbols[index].parent
    return index


def _stored(store: CodeStore, file_id: int, symbol: Optional[ParsedSymbol]) -> Optional[Symbol]:
    if symbol is None:
        return None
    for stored in store.outline(file_id):
        if stored.kind == symbol.kind and stored.qualified == symbol.qualified and stored.params == symbol.params:
            return stored
    return None


def _parse_with_sentinel(path: str, buffer: str, line: int, expression: Expression, col: int):
    """Parses the buffer with the expression replaced by a sentinel call; returns (parsed, sentinel ref)."""
    lines = buffer.split("\n")
    current = lines[line - 1]
    head = current[:expression.start_col - 1]
    call = f"{expression.receiver}.{SENTINEL}()" if expression.receiver else f"{SENTINEL}()"
    if expression.kind == "new":
        call = f"new {SENTINEL}()"
    rest = current[col - 1:]
    for tail in (rest, ";" if path.endswith(".java") else ""):
        lines[line - 1] = head + call + tail
        parsed = parse(path, "\n".join(lines).encode("utf-8"))
        ref = next((r for r in parsed.refs if r.name == SENTINEL and r.line == line), None)
        if ref is not None:
            return parsed, ref
    return parse(path, buffer.encode("utf-8")), None


def context_at(store: CodeStore, file_id: int, buffer: str, line: int, col: int) -> Context:
    """The context of the cursor in an unsaved buffer of a file of the index."""
    file = store.file(file_id)
    if file is None:
        raise ValueError("That file is no longer in the code index.")
    lines = buffer.split("\n")
    line = max(1, min(line, len(lines)))
    col = max(1, min(col, len(lines[line - 1]) + 1))
    prefix = lines[line - 1][:col - 1]
    java = file.language == JAVA
    expression = read_expression(prefix, file.language)

    parsed, sentinel = _parse_with_sentinel(file.path, buffer, line, expression, col)
    enclosing_index = sentinel.scope if sentinel is not None else _enclosing_index(parsed, line)
    enclosing_symbol = parsed.symbols[enclosing_index] if enclosing_index is not None else None
    type_index = _enclosing_type_index(parsed, enclosing_index)
    stored = _stored(store, file_id, enclosing_symbol)
    stored_type = _stored(store, file_id, parsed.symbols[type_index] if type_index is not None else None)
    enclosing = None
    if enclosing_symbol is not None:
        enclosing = Enclosing(stored.id if stored else None, enclosing_symbol.kind, enclosing_symbol.qualified,
                              enclosing_symbol.name, enclosing_symbol.type, parsed.package if java else file.package,
                              enclosing_symbol.line, enclosing_symbol.end_line, stored_type.id if stored_type else None)

    # The receiver's chain, with a field declared only in the buffer resolved from its declared type
    chain = sentinel.chain if sentinel is not None else ""
    if chain.startswith("N:") and type_index is not None:
        base = chain[2:].split(".")[0]
        declared = next((s.type for s in parsed.symbols if s.kind == "field" and s.parent == type_index and s.name == base and s.type), "")
        if declared and not _stored(store, file_id, next(s for s in parsed.symbols if s.kind == "field" and s.parent == type_index and s.name == base)):
            chain = f"T:{declared}" + chain[2 + len(base):]
    expression.chain = chain
    receiver_type = None
    if expression.receiver:
        linker = store.linker(file.codebase_id)
        from_symbol = (stored.id if stored else None) or (stored_type.id if stored_type else None)
        target, carried = linker._follow(chain, file_id, from_symbol, java) if chain else (None, "")
        if isinstance(target, int):
            symbol = store.symbol(target)
            receiver_type = TypeRef(target, symbol.qualified, symbol.path, "resolved", carried)
        elif isinstance(target, str):
            receiver_type = TypeRef(None, target, "", "resolved", carried)

    neighbours = Neighbours(shape=sentinel.shape if sentinel is not None else "")
    if enclosing_index is not None:
        for ref in parsed.refs:
            if ref.scope == enclosing_index and ref.name != SENTINEL:
                (neighbours.calls if ref.kind in ("call", "new") else neighbours.types).add(ref.name)
        body = "\n".join(lines[enclosing_symbol.line - 1:enclosing_symbol.end_line])
        neighbours.identifiers = {w for w in re.findall(_WORD, body) if w not in _KEYWORDS and w != SENTINEL} - neighbours.names()
    locals_ = dict(parsed.locals.get(enclosing_index, {})) if enclosing_index is not None else {}
    digest = hashlib.sha1("|".join([str(file.codebase_id), file.path, enclosing.qualified if enclosing else "",
                                    expression.kind, expression.name, expression.partial, expression.receiver,
                                    receiver_type.qualified if receiver_type else ""]).encode()).hexdigest()[:16]
    return Context(file_id, file.codebase_id, file.language, file.path, line, col, expression, enclosing, receiver_type,
                   neighbours, [i.spec for i in parsed.imports], locals_, parsed, enclosing_index, digest)
