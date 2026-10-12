"""
TypeScript declaration files read as library symbols (ADR-024): the `.d.ts` files of the packages
a `package.json` declares, found in `node_modules`, and TypeScript's own `lib.*.d.ts` for the
built-ins and the browser. Read with the TypeScript grammar already in use (tree-sitter), so
nothing is run and Node.js isn't needed.

What is kept, per package: exported classes, interfaces, functions, constants and type aliases,
with members, parameter counts and return types. Names in a return type that the package itself
declares, or imports from another package, are written in the encoded form the linker reads from
any file ("=rxjs#Observable<T>"), so chains continue through them.
"""
import json
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Set, Tuple

from tree_sitter import Language, Node, Parser
import tree_sitter_typescript

from src.code.parser import _declared_type_parameters, _text, _ts_type

TYPESCRIPT = "typescript"
LIB_FILES = ("lib.es5.d.ts", "lib.es2015.core.d.ts", "lib.es2015.collection.d.ts", "lib.es2015.iterable.d.ts",
             "lib.es2015.promise.d.ts", "lib.es2015.symbol.wellknown.d.ts", "lib.es2017.object.d.ts", "lib.es2017.string.d.ts",
             "lib.es2018.asynciterable.d.ts", "lib.es2018.promise.d.ts", "lib.es2019.array.d.ts", "lib.es2020.promise.d.ts",
             "lib.es2022.array.d.ts", "lib.dom.d.ts")
MAX_FILES = 400              # Per package: a package with more declaration files than this is read partially
_parser: Optional[Parser] = None


@dataclass
class Row:
    """One code_library row: a type of the package, or a member of one."""
    qualified: str              # "pkg#Name" for types and aliases, "pkg#Name.member" for members, "pkg#fn" for functions
    kind: str                   # class, interface, enum, type, alias, function, variable, method, field
    name: str
    owner: str = ""             # Members: "pkg#Name"; functions and constants: the package ("" for globals)
    params: int = -1
    returns: str = ""           # Return or declared type, names encoded where known; aliases: the type aliased (encoded)
    supers: str = ""            # Types: what they extend or implement, comma-separated, encoded without "="
    type_params: str = ""       # Types: "T, U"; methods and functions: their own
    signature: str = ""


@dataclass
class _File:
    path: Path
    exports: Dict[str, str] = field(default_factory=dict)       # Exported name → declared name in this file, or "<module>:name"
    declared: Set[str] = field(default_factory=set)
    imports: Dict[str, str] = field(default_factory=dict)       # Local name → "pkg#Name" or "<module>:name" (relative)
    star_exports: List[str] = field(default_factory=list)       # Modules re-exported whole


def _parse(source: bytes) -> Node:
    global _parser
    if _parser is None:
        _parser = Parser(Language(tree_sitter_typescript.language_typescript()))
    return _parser.parse(source).root_node


def _string(node: Optional[Node]) -> str:
    return "".join(_text(c) for c in node.named_children if c.type in ("string_fragment", "escape_sequence")) if node is not None else ""


def package_entries(folder: Path) -> List[Path]:
    """The declaration files a package is entered through: its types field, the exports map's entries, index.d.ts, secondary entry points."""
    entries: List[Path] = []
    try:
        data = json.loads((folder / "package.json").read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        data = {}

    def add(relative: Optional[str]) -> None:
        if not relative or not isinstance(relative, str):
            return
        relative = relative.lstrip("./") if relative.startswith("./") else relative
        candidates = [relative] if relative.endswith(".d.ts") else [re.sub(r"\.[cm]?js$", "", relative) + ".d.ts", relative + ".d.ts",
                                                                     posixpath.join(relative, "index.d.ts")]
        for candidate in candidates:
            path = folder / candidate
            if path.is_file() and path not in entries:
                entries.append(path)
                return

    add(data.get("types") or data.get("typings") or data.get("main"))
    exports = data.get("exports")

    def walk(value) -> None:
        if isinstance(value, str):
            add(value)
        elif isinstance(value, dict):
            for key in ("types", "typings", "import", "default"):
                if key in value:
                    walk(value[key])
                    return
            for sub in value.values():
                walk(sub)
    if isinstance(exports, (dict, str)):
        walk(exports)
    if not entries:
        add("index.d.ts")
    # Secondary entry points (Angular's "@angular/common/http"): a folder with its own package.json or index.d.ts
    try:
        for sub in sorted(folder.iterdir()):
            if sub.is_dir() and not sub.name.startswith((".", "_")) and sub.name != "node_modules":
                if (sub / "package.json").is_file():
                    entries += [e for e in package_entries(sub) if e not in entries]
                elif (sub / "index.d.ts").is_file() and (sub / "index.d.ts") not in entries:
                    entries.append(sub / "index.d.ts")
    except OSError:
        pass
    return entries


class _Reader:
    def __init__(self, package: str, root: Path):
        self.package, self.root = package, root
        self.prefix = f"{package}#" if package else "#"
        self.files: Dict[Path, _File] = {}
        self.rows: List[Row] = []
        self.queue: List[Path] = []
        self.pending: List[Tuple[_File, Node, str, bool]] = []   # (file, declaration, local name, exported) to emit after names are known

    # -- Pass 1: declarations and exports of each file reachable from the entries ---------------

    def read(self, entries: List[Path], globals_only: bool = False) -> List[Row]:
        self.queue = list(entries)
        while self.queue and len(self.files) < MAX_FILES:
            path = self.queue.pop(0)
            if path in self.files:
                continue
            try:
                source = path.read_bytes()
            except OSError:
                continue
            self.files[path] = this = _File(path)
            self.collect(this, _parse(source), globals_only)
        self.emit()
        return self.rows

    def module(self, this: _File, spec: str) -> Optional[Path]:
        if not spec.startswith("."):
            return None
        base = (this.path.parent / spec).resolve()
        for candidate in (Path(str(base) + ".d.ts"), base / "index.d.ts", Path(re.sub(r"\.js$", ".d.ts", str(base)))):
            if candidate.is_file():
                return candidate
        return None

    def collect(self, this: _File, root: Node, globals_only: bool) -> None:
        for node in root.named_children:
            kind = node.type
            if kind == "import_statement":
                spec = _string(node.child_by_field_name("source"))
                target = self.module(this, spec)
                if target is not None:
                    self.queue.append(target)
                clause = next((c for c in node.named_children if c.type == "import_clause"), None)
                for part in clause.named_children if clause is not None else []:
                    if part.type == "named_imports":
                        for item in part.named_children:
                            imported = _text(item.child_by_field_name("name"))
                            local = _text(item.child_by_field_name("alias")) or imported
                            this.imports[local] = f"{target}:{imported}" if target is not None else f"{spec}#{imported}"
                    elif part.type == "identifier":
                        this.imports[_text(part)] = f"{spec}#default"
            elif kind == "export_statement":
                source = node.child_by_field_name("source")
                if source is not None:   # export * from, export { a as b } from
                    target = self.module(this, _string(source))
                    if target is None:
                        continue
                    self.queue.append(target)
                    clause = next((c for c in node.named_children if c.type == "export_clause"), None)
                    if clause is None:
                        this.star_exports.append(str(target))
                    else:
                        for item in clause.named_children:
                            name = _text(item.child_by_field_name("name"))
                            this.exports[_text(item.child_by_field_name("alias")) or name] = f"{target}:{name}"
                    continue
                declaration = node.child_by_field_name("declaration")
                if declaration is not None and declaration.type == "ambient_declaration":   # export declare class X
                    for inner in declaration.named_children:
                        self.declaration(this, inner, True)
                elif declaration is not None:
                    self.declaration(this, declaration, True)
                else:
                    clause = next((c for c in node.named_children if c.type == "export_clause"), None)
                    for item in clause.named_children if clause is not None else []:
                        name = _text(item.child_by_field_name("name"))
                        this.exports[_text(item.child_by_field_name("alias")) or name] = name
            elif kind == "ambient_declaration":   # declare class X / declare function f / declare var x (global, or module-private)
                for inner in node.named_children:
                    self.declaration(this, inner, False)
            elif kind in ("interface_declaration", "type_alias_declaration", "class_declaration", "abstract_class_declaration",
                          "enum_declaration", "function_signature"):
                self.declaration(this, node, globals_only)   # Top-level in a global script (lib.dom.d.ts), or module-private

    def declaration(self, this: _File, node: Node, exported: bool) -> None:
        if node.type not in ("class_declaration", "abstract_class_declaration", "function_signature", "interface_declaration",
                             "type_alias_declaration", "enum_declaration", "lexical_declaration", "variable_declaration"):
            return
        if node.type in ("lexical_declaration", "variable_declaration"):
            for declarator in node.named_children:
                if declarator.type == "variable_declarator":
                    self.pending.append((this, declarator, _text(declarator.child_by_field_name("name")), exported))
                    this.declared.add(_text(declarator.child_by_field_name("name")))
            return
        name = _text(node.child_by_field_name("name"))
        if not name:
            return
        this.declared.add(name)
        self.pending.append((this, node, name, exported))
        if exported:
            this.exports.setdefault(name, name)

    # -- Pass 2: rows, with names resolved to encoded forms --------------------------------------

    def exported_name(self, this: _File, local: str) -> Optional[str]:
        """The name a file-local declaration is exported under from the package, if it is: a re-export's name wins."""
        for other in self.files.values():   # export { Page as PageOf } from './page'
            for exported, target in other.exports.items():
                if target == f"{this.path}:{local}":
                    return exported
        for exported, target in this.exports.items():
            if target == local:
                return exported
        return None

    def encode(self, this: _File, name: str) -> str:
        """A simple type name as the linker's encoded target: declared in the package, imported, or left as written."""
        if name in this.declared:
            exported = self.exported_name(this, name) if self.package else name
            return f"={self.prefix}{exported or name}"
        if not self.package and any(name in other.declared for other in self.files.values()):   # Globals see each other
            return f"={self.prefix}{name}"
        target = this.imports.get(name)
        if target is None:
            return name
        if ":" in target and not target.startswith("@") and "#" not in target:   # Another file of the package
            path, local = target.rsplit(":", 1)
            other = self.files.get(Path(path))
            if other is not None and local in other.declared:
                exported = self.exported_name(other, local)
                return f"={self.prefix}{exported or local}"
            return name
        return f"={target}"

    def encode_type(self, this: _File, text: str) -> str:
        """Type names in a type's text encoded: "Observable<T>" → "=rxjs#Observable<T>"; the rest as written."""
        if not text:
            return ""
        def replace(match: re.Match) -> str:
            word = match.group(0)
            return self.encode(this, word) if word[:1].isupper() else word
        return re.sub(r"(?<![\w$#=.@/])[A-Za-z_$][\w$]*", replace, text)

    def emit(self) -> None:
        for this, node, local, exported in self.pending:
            if self.package and not exported:
                continue
            exported_as = (self.exported_name(this, local) or local) if self.package else local
            qualified = f"{self.prefix}{exported_as}"
            kind = node.type
            if kind in ("class_declaration", "abstract_class_declaration", "interface_declaration", "enum_declaration"):
                self.type_rows(this, node, qualified, local, "interface" if kind == "interface_declaration" else "enum" if kind == "enum_declaration" else "class")
            elif kind == "type_alias_declaration":
                aliased = _ts_type(node.child_by_field_name("value"))
                simple = aliased.split("<")[0].strip()
                encoded = self.encode(this, simple) if re.fullmatch(r"[A-Za-z_$][\w$]*", simple) else ""
                self.rows.append(Row(qualified, "alias" if encoded.startswith("=") else "type", exported_as, returns=encoded[1:] if encoded.startswith("=") else "",
                                     type_params=_declared_type_parameters(node.child_by_field_name("type_parameters")),
                                     signature=f"type {exported_as} = {aliased[:80]}"))
            elif kind == "function_signature":
                parameters = node.child_by_field_name("parameters")
                self.rows.append(Row(qualified, "function", exported_as, self.package, parameters.named_child_count if parameters is not None else 0,
                                     self.encode_type(this, _ts_type(node.child_by_field_name("return_type"))), "",
                                     _declared_type_parameters(node.child_by_field_name("type_parameters")),
                                     f"{exported_as}({parameters.named_child_count if parameters is not None else 0} args)"))
            elif kind == "variable_declarator":
                declared = _ts_type(node.child_by_field_name("type"))
                self.rows.append(Row(qualified, "variable", exported_as, self.package, -1, self.encode_type(this, declared), signature=f"{declared} {exported_as}"))

    def type_rows(self, this: _File, node: Node, qualified: str, local: str, kind: str) -> None:
        supers = []
        for child in node.named_children:
            if child.type == "class_heritage":
                for clause in child.named_children:
                    for item in clause.named_children:
                        if item.type != "type_arguments":
                            supers.append(self.encode(this, _text(item.child_by_field_name("name") or item).split("<")[0]))
            elif child.type in ("extends_type_clause", "extends_clause"):
                for item in child.named_children:
                    if item.type != "type_arguments":
                        supers.append(self.encode(this, _text(item.child_by_field_name("name") or item).split("<")[0]))
        self.rows.append(Row(qualified, kind, qualified.split("#")[-1], "", -1, "", ",".join(s[1:] for s in supers if s.startswith("=")),
                             _declared_type_parameters(node.child_by_field_name("type_parameters")), f"{kind} {local}"))
        body = node.child_by_field_name("body")
        if body is None:
            return
        seen: Set[Tuple[str, int]] = set()
        for member in body.named_children:
            if member.type in ("method_signature", "abstract_method_signature", "method_definition"):
                name = _text(member.child_by_field_name("name"))
                parameters = member.child_by_field_name("parameters")
                params = parameters.named_child_count if parameters is not None else 0
                if not name or (name, params) in seen or any(c.type == "accessibility_modifier" and _text(c) == "private" for c in member.children):
                    continue
                seen.add((name, params))
                returns = _ts_type(member.child_by_field_name("return_type"))
                self.rows.append(Row(f"{qualified}.{name}", "method", name, qualified, params, self.encode_type(this, returns), "",
                                     _declared_type_parameters(member.child_by_field_name("type_parameters")), f"{returns} {name}({params} args)".strip()))
            elif member.type in ("property_signature", "public_field_definition"):
                name = _text(member.child_by_field_name("name"))
                if not name or (name, -1) in seen or any(c.type == "accessibility_modifier" and _text(c) == "private" for c in member.children):
                    continue
                seen.add((name, -1))
                declared = _ts_type(member.child_by_field_name("type"))
                self.rows.append(Row(f"{qualified}.{name}", "field", name, qualified, -1, self.encode_type(this, declared), signature=f"{declared} {name}".strip()))


def read_package(folder: Path, package: str) -> List[Row]:
    """The public declarations of one installed package."""
    entries = package_entries(folder)
    return _Reader(package, folder).read(entries) if entries else []


def read_typescript_lib(folder: Path) -> List[Row]:
    """TypeScript's built-in and browser declarations (`node_modules/typescript/lib`): global, so named "#Array", "#fetch"."""
    files = [folder / name for name in LIB_FILES if (folder / name).is_file()]
    return _Reader("", folder).read(files, globals_only=False) if files else []


def find_package(root: Path, manifest_dir: str, name: str) -> Optional[Path]:
    """The installed folder of a declared package: the nearest node_modules up from the manifest."""
    folder = (root / manifest_dir).resolve() if manifest_dir else root.resolve()
    for _ in range(6):
        candidate = folder / "node_modules" / name
        if (candidate / "package.json").is_file():
            return candidate
        if folder.parent == folder or folder == root.resolve().parent:
            break
        folder = folder.parent
    return None


def declaration_sources(root: Path, declared: List[Tuple[str, str]]) -> Iterator[Tuple[Path, str]]:
    """(folder, package name) for each declared npm package found installed, plus TypeScript's lib folder once."""
    seen: Set[Path] = set()
    typescript: Optional[Path] = None
    for manifest, name in declared:
        folder = find_package(root, posixpath.dirname(manifest), name)
        if folder is None or folder in seen:
            continue
        seen.add(folder)
        if name == "typescript":
            typescript = folder / "lib"
            continue
        types = find_package(root, posixpath.dirname(manifest), f"@types/{name}") if not name.startswith("@types/") else None
        if types is not None and types not in seen:
            seen.add(types)
            yield types, name
        yield folder, name
    if typescript is None:
        for manifest, _ in declared:
            found = find_package(root, posixpath.dirname(manifest), "typescript")
            if found is not None:
                typescript = found / "lib"
                break
    if typescript is not None and typescript.is_dir():
        yield typescript, ""
