"""
Reads one source file (Java, JavaScript, TypeScript, JSX/TSX) into the facts the code index keeps:
the symbols it declares, the references it makes, what it imports, and the HTTP endpoints it serves
or calls.

Parsing is done with tree-sitter: a real parser (not pattern matching, and not a language model) that
runs locally and still gives a usable tree for files with syntax errors. Only facts visible in the
file itself are recorded here. Working out what each reference points to, which needs the other
files, is the index's job (see store.py).
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import tree_sitter_java
import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

JAVA, JAVASCRIPT, TYPESCRIPT = "java", "javascript", "typescript"
# Extension → (language, grammar)
EXTENSIONS = {
    ".java": (JAVA, "java"),
    ".js": (JAVASCRIPT, "javascript"), ".jsx": (JAVASCRIPT, "javascript"),
    ".mjs": (JAVASCRIPT, "javascript"), ".cjs": (JAVASCRIPT, "javascript"),
    ".ts": (TYPESCRIPT, "typescript"), ".mts": (TYPESCRIPT, "typescript"), ".cts": (TYPESCRIPT, "typescript"),
    ".tsx": (TYPESCRIPT, "tsx"),
}
_GRAMMARS = {
    "java": tree_sitter_java.language,
    "javascript": tree_sitter_javascript.language,   # Includes JSX
    "typescript": tree_sitter_typescript.language_typescript,
    "tsx": tree_sitter_typescript.language_tsx,
}
_parsers: Dict[str, Parser] = {}

TYPE_KINDS = ("class", "interface", "enum", "record", "annotation", "type")
HTTP_METHODS = {"get": "GET", "post": "POST", "put": "PUT", "delete": "DELETE", "patch": "PATCH",
                "head": "HEAD", "options": "OPTIONS"}
_SIGNATURE_CHARS = 200


@dataclass
class ParsedSymbol:
    kind: str                   # class, interface, enum, record, annotation, type, method, constructor, field, function, variable
    name: str
    qualified: str              # Java: "pkg.Outer.Inner", "pkg.Type#method"; JS/TS: "Class#method", "name" (within its file)
    parent: Optional[int]       # Index of the enclosing symbol in ParsedFile.symbols
    line: int
    end_line: int
    signature: str              # The declaration up to its body, on one line
    params: int = -1            # Parameter count for methods and functions
    exported: bool = False      # Java: public; JS/TS: exported from its module
    default: bool = False       # JS/TS: the module's default export


@dataclass
class ParsedRef:
    kind: str                   # call, new, extends, implements, type, annotation, jsx, use
    name: str                   # What's referred to, as written: a method, function or type name
    line: int
    col: int
    scope: Optional[int]        # Index of the symbol the reference is made in
    receiver: str = ""          # Java calls: the declared type of what it's called on, "this" or "super".
                                # JS/TS: the name it's reached through ("axios" in axios.get(), "this")
    args: int = -1


@dataclass
class ParsedImport:
    spec: str                   # Java: "java.util.List", "java.util.*"; JS/TS: the module specifier
    line: int
    static: bool = False        # Java: import static
    names: Dict[str, str] = field(default_factory=dict)  # JS/TS: local name → imported name ("default", "*" or a name)


@dataclass
class ParsedEndpoint:
    side: str                   # "server" (the code handles it) or "client" (the code calls it)
    method: str                 # GET, POST…; "ANY" when it isn't stated
    path: str                   # As written, with variable parts as {}
    line: int
    scope: Optional[int]
    framework: str              # spring, jax-rs, express, fetch, axios, ajax, http


@dataclass
class ParsedFile:
    language: str
    package: str = ""           # Java package ("" for JS/TS: the index uses the file's folder)
    symbols: List[ParsedSymbol] = field(default_factory=list)
    refs: List[ParsedRef] = field(default_factory=list)
    imports: List[ParsedImport] = field(default_factory=list)
    endpoints: List[ParsedEndpoint] = field(default_factory=list)
    has_errors: bool = False    # The file has syntax errors; what could be read is still recorded


def language_of(path: str) -> Optional[str]:
    """The language a file is parsed as, by extension; None for files the index doesn't read."""
    match = re.search(r"\.[A-Za-z]+$", path)
    entry = EXTENSIONS.get(match.group(0).lower()) if match else None
    return entry[0] if entry else None


def parse(path: str, source: bytes) -> ParsedFile:
    language, grammar = EXTENSIONS[re.search(r"\.[A-Za-z]+$", path).group(0).lower()]
    if grammar not in _parsers:
        _parsers[grammar] = Parser(Language(_GRAMMARS[grammar]()))
    tree = _parsers[grammar].parse(source)
    result = ParsedFile(language=language, has_errors=tree.root_node.has_error)
    (_JavaReader if language == JAVA else _ScriptReader)(result).read(tree.root_node)
    return result


def _text(node: Optional[Node]) -> str:
    return node.text.decode("utf-8", "replace") if node is not None else ""


def _signature(node: Node, body: Optional[Node]) -> str:
    """A declaration up to (not including) its body, on one line."""
    raw = node.text[: body.start_byte - node.start_byte] if body is not None else node.text
    text = " ".join(raw.decode("utf-8", "replace").split())
    return text[:_SIGNATURE_CHARS] + ("…" if len(text) > _SIGNATURE_CHARS else "")


def _string(node: Optional[Node]) -> Optional[str]:
    """
    The text of a string-like expression used as a URL path, with variable parts as {}: a string
    literal, a template (`/users/${id}`) or a concatenation that starts with a string ('/users/' + id).
    None for anything else.
    """
    if node is None:
        return None
    if node.type in ("string", "string_literal"):
        return "".join(_text(c) for c in node.named_children if c.type in ("string_fragment", "escape_sequence"))
    if node.type == "template_string":
        return "".join("{}" if c.type == "template_substitution" else _text(c) for c in node.named_children)
    if node.type == "binary_expression":
        left = _string(node.child_by_field_name("left"))
        if left is not None:
            right = _string(node.child_by_field_name("right"))
            return left + (right if right is not None else "{}")
    if node.type == "parenthesized_expression" and node.named_child_count == 1:
        return _string(node.named_children[0])
    return None


def _looks_like_path(text: Optional[str]) -> bool:
    return bool(text) and (text.startswith(("/", "http://", "https://", "{}/")) or re.match(r"^[\w-]+/[\w{}/-]*$", text) is not None)


def _type_parameters(root: Node) -> set:
    """Names declared as type parameters anywhere in a file (<T>, <K, V>): uses of them aren't references to types."""
    names, stack = set(), [root]
    while stack:
        node = stack.pop()
        if node.type == "type_parameter":
            name = node.child_by_field_name("name") or (node.named_children[0] if node.named_children else None)
            names.add(_text(name))
        else:
            stack.extend(node.named_children)
    return names


class _Reader:
    def __init__(self, result: ParsedFile):
        self.out = result
        self.generics: set = set()

    def symbol(self, kind: str, name: str, qualified: str, parent: Optional[int], node: Node,
               body: Optional[Node] = None, **more) -> int:
        self.out.symbols.append(ParsedSymbol(kind, name, qualified, parent, node.start_point[0] + 1,
                                             node.end_point[0] + 1, _signature(node, body), **more))
        return len(self.out.symbols) - 1

    def ref(self, kind: str, name: str, node: Node, scope: Optional[int], receiver: str = "", args: int = -1) -> None:
        if name:
            self.out.refs.append(ParsedRef(kind, name, node.start_point[0] + 1, node.start_point[1] + 1, scope,
                                           receiver, args))

    def endpoint(self, side: str, method: str, path: str, node: Node, scope: Optional[int], framework: str) -> None:
        self.out.endpoints.append(ParsedEndpoint(side, method, path, node.start_point[0] + 1, scope, framework))


# ---- Java ---------------------------------------------------------------------------------------

_JAVA_TYPES = {"class_declaration": "class", "interface_declaration": "interface", "enum_declaration": "enum",
               "record_declaration": "record", "annotation_type_declaration": "annotation"}
_SPRING_MAPPINGS = {"GetMapping": "GET", "PostMapping": "POST", "PutMapping": "PUT", "DeleteMapping": "DELETE",
                    "PatchMapping": "PATCH", "RequestMapping": "ANY"}
_JAXRS_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}


def _java_type_name(node: Optional[Node]) -> str:
    """The name of a type as written, without type arguments or array brackets: "List", "Map.Entry"."""
    if node is None:
        return ""
    if node.type in ("type_identifier", "scoped_type_identifier"):
        return _text(node)
    if node.type in ("generic_type", "array_type", "annotated_type"):
        return next((name for c in node.named_children if (name := _java_type_name(c))), "")
    return ""


def join_paths(prefix: str, path: str) -> str:
    return "/" + "/".join(part.strip("/") for part in (prefix, path) if part.strip("/"))


class _JavaReader(_Reader):
    def read(self, root: Node) -> None:
        self.generics = _type_parameters(root)
        for node in root.named_children:
            if node.type == "package_declaration":
                self.out.package = next((_text(c) for c in node.named_children
                                         if c.type in ("scoped_identifier", "identifier")), "")
            elif node.type == "import_declaration":
                name = next((_text(c) for c in node.named_children if c.type in ("scoped_identifier", "identifier")), "")
                wildcard = any(c.type == "asterisk" for c in node.named_children)
                self.out.imports.append(ParsedImport(name + (".*" if wildcard else ""), node.start_point[0] + 1,
                                                     static=any(c.type == "static" for c in node.children)))
            else:
                self.visit(node, None, self.out.package, {}, "")

    def visit(self, node: Node, scope: Optional[int], container: str, variables: Dict[str, str], prefix: str) -> None:
        """
        `scope`: the enclosing symbol; `container`: the qualified name of the enclosing type (or the
        package); `variables`: names in scope → their declared type; `prefix`: the enclosing type's
        URL prefix (@RequestMapping on the class).
        """
        kind = node.type
        if kind in _JAVA_TYPES:
            return self.type_declaration(node, scope, container, variables)
        if kind in ("method_declaration", "constructor_declaration", "compact_constructor_declaration"):
            return self.method(node, scope, container, variables, prefix)
        if kind == "field_declaration":
            type_name = _java_type_name(node.child_by_field_name("type"))
            for declarator in node.children_by_field_name("declarator"):
                name = _text(declarator.child_by_field_name("name"))
                variables[name] = type_name
                self.symbol("field", name, f"{container}#{name}", scope, node, declarator.child_by_field_name("value"))
        elif kind == "enum_constant":
            name = _text(node.child_by_field_name("name"))
            self.symbol("field", name, f"{container}#{name}", scope, node, node.child_by_field_name("body"))
        elif kind in ("local_variable_declaration", "formal_parameter", "spread_parameter", "enhanced_for_statement",
                      "catch_formal_parameter", "resource"):
            type_name = _java_type_name(node.child_by_field_name("type")) or next(
                (_java_type_name(c) for c in node.named_children if c.type == "catch_type"), "")
            names = [d.child_by_field_name("name") for d in node.children_by_field_name("declarator")]
            names.append(node.child_by_field_name("name"))
            names += [c.child_by_field_name("name") for c in node.named_children if c.type == "variable_declarator"]
            for name in names:
                if name is not None and type_name and type_name != "var":
                    variables[_text(name)] = type_name
        elif kind == "method_invocation":
            self.ref("call", _text(node.child_by_field_name("name")), node.child_by_field_name("name"), scope,
                     self.receiver(node.child_by_field_name("object"), variables),
                     node.child_by_field_name("arguments").named_child_count)
        elif kind == "method_reference":   # Type::method, this::method
            target = node.named_children[0] if node.named_children else None
            name = node.named_children[-1] if node.named_child_count > 1 else None
            if name is not None and name.type == "identifier":
                self.ref("call", _text(name), name, scope, self.receiver(target, variables))
        elif kind == "object_creation_expression":
            type_node = node.child_by_field_name("type")
            arguments = node.child_by_field_name("arguments")
            self.ref("new", _java_type_name(type_node), type_node, scope,
                     args=arguments.named_child_count if arguments is not None else -1)
            for child in node.named_children:
                if child != type_node:   # Its arguments, and an anonymous class's body
                    self.visit(child, scope, container, variables, prefix)
            return
        elif kind in ("marker_annotation", "annotation"):
            self.ref("annotation", _text(node.child_by_field_name("name")), node, scope)
        elif kind in ("type_identifier", "scoped_type_identifier"):
            if _text(node) != "var" and _text(node) not in self.generics:
                self.ref("type", _text(node), node, scope)
            return
        elif kind == "lambda_expression":
            variables = dict(variables)

        for child in node.named_children:
            self.visit(child, scope, container, variables, prefix)

    def receiver(self, node: Optional[Node], variables: Dict[str, str]) -> str:
        """What a method is called on, as a type name where that's visible in this file."""
        if node is None or node.type == "this":
            return "this"
        if node.type == "super":
            return "super"
        if node.type == "identifier":
            name = _text(node)
            return variables.get(name) or (name if name[:1].isupper() else "")  # A variable's type, or a static call
        if node.type == "field_access" and node.child_by_field_name("object").type == "this":
            return variables.get(_text(node.child_by_field_name("field")), "")
        if node.type in ("scoped_identifier", "field_access"):
            text = _text(node)
            return text if re.fullmatch(r"(?:[a-z_]\w*\.)*[A-Z]\w*(?:\.[A-Z]\w*)*", text) else ""  # pkg.Type.method()
        return ""

    def type_declaration(self, node: Node, scope: Optional[int], container: str, variables: Dict[str, str]) -> None:
        name = _text(node.child_by_field_name("name"))
        qualified = f"{container}.{name}" if container else name
        body = node.child_by_field_name("body")
        modifiers = next((c for c in node.named_children if c.type == "modifiers"), None)
        index = self.symbol(_JAVA_TYPES[node.type], name, qualified, scope, node, body,
                            exported="public" in _text(modifiers).split())
        for field_name, kind in (("superclass", "extends"), ("interfaces", "implements")):
            self.supertypes(node.child_by_field_name(field_name), kind, index)
        for child in node.named_children:
            if child.type == "extends_interfaces":   # interface A extends B, C
                self.supertypes(child, "extends", index)

        prefix = ""
        if modifiers is not None:
            self.visit(modifiers, index, qualified, {}, "")
            for annotation in modifiers.named_children:
                if _text(annotation.child_by_field_name("name")) in ("RequestMapping", "Path"):
                    prefix = next(iter(self.annotation_strings(annotation)), "")
        members: Dict[str, str] = dict(variables)   # An inner class sees the outer class's fields
        for child in node.named_children:
            if child.type in ("formal_parameters", "type_parameters"):   # A record's components
                self.visit(child, index, qualified, members, prefix)
        if body is not None:
            # Fields first: methods above a field's declaration still call through it
            for child in body.named_children:
                if child.type == "field_declaration":
                    type_name = _java_type_name(child.child_by_field_name("type"))
                    for declarator in child.children_by_field_name("declarator"):
                        members[_text(declarator.child_by_field_name("name"))] = type_name
            self.visit(body, index, qualified, members, prefix)

    def supertypes(self, node: Optional[Node], kind: str, index: int) -> None:
        if node is None:
            return
        found: List[Node] = []

        def collect(n: Node) -> None:
            if n.type in ("type_identifier", "scoped_type_identifier", "generic_type"):
                found.append(n)
            else:
                for c in n.named_children:
                    collect(c)
        collect(node)
        for type_node in found:
            self.ref(kind, _java_type_name(type_node), type_node, index)
            if type_node.type == "generic_type":   # Type arguments are ordinary type uses
                for child in type_node.named_children[1:]:
                    self.visit(child, index, "", {}, "")

    def method(self, node: Node, scope: Optional[int], container: str, variables: Dict[str, str], prefix: str) -> None:
        constructor = node.type != "method_declaration"
        name = _text(node.child_by_field_name("name"))
        parameters = node.child_by_field_name("parameters")
        body = node.child_by_field_name("body")
        modifiers = next((c for c in node.named_children if c.type == "modifiers"), None)
        index = self.symbol("constructor" if constructor else "method", name, f"{container}#{name}", scope, node, body,
                            params=parameters.named_child_count if parameters is not None else 0,
                            exported="public" in _text(modifiers).split())
        if modifiers is not None:
            self.spring_or_jaxrs(modifiers, prefix, index)
        local = dict(variables)
        for child in node.named_children:
            self.visit(child, index, container, local, prefix)

    @staticmethod
    def annotation_strings(annotation: Node) -> List[str]:
        """The path strings of a mapping annotation: @X("/a"), @X(value = "/a"), @X(path = {"/a", "/b"})."""
        arguments = annotation.child_by_field_name("arguments")
        if arguments is None:
            return []
        values = []
        for arg in arguments.named_children:
            if arg.type == "element_value_pair":
                if _text(arg.child_by_field_name("key")) not in ("value", "path"):
                    continue
                arg = arg.child_by_field_name("value")
            items = arg.named_children if arg.type == "element_value_array_initializer" else [arg]
            values += [s for s in (_string(item) for item in items) if s is not None]
        return values

    def spring_or_jaxrs(self, modifiers: Node, prefix: str, index: int) -> None:
        jaxrs_method, jaxrs_path = "", None
        for annotation in modifiers.named_children:
            name = _text(annotation.child_by_field_name("name"))
            if name in _SPRING_MAPPINGS:
                method = _SPRING_MAPPINGS[name]
                if name == "RequestMapping":
                    stated = re.search(r"RequestMethod\.([A-Z]+)", _text(annotation))
                    method = stated.group(1) if stated else "ANY"
                for path in self.annotation_strings(annotation) or [""]:
                    self.endpoint("server", method, join_paths(prefix, path), annotation, index, "spring")
            elif name in _JAXRS_METHODS:
                jaxrs_method = name
            elif name == "Path":
                jaxrs_path = next(iter(self.annotation_strings(annotation)), "")
        if jaxrs_method:
            self.endpoint("server", jaxrs_method, join_paths(prefix, jaxrs_path or ""), modifiers, index, "jax-rs")


# ---- JavaScript / TypeScript --------------------------------------------------------------------

_FUNCTIONS = ("arrow_function", "function_expression", "function", "generator_function")
_SCRIPT_TYPES = {"class_declaration": "class", "abstract_class_declaration": "class", "class": "class",
                 "interface_declaration": "interface", "type_alias_declaration": "type", "enum_declaration": "enum"}
_SERVER_RECEIVER = re.compile(r"^(?:app|router|routes?|server|api)$|(?:Router|Routes|App)$", re.IGNORECASE)


class _ScriptReader(_Reader):
    def read(self, root: Node) -> None:
        self.bindings: Dict[str, str] = {}   # Imported local names (a use of one is a reference worth keeping)
        self.exports: List[Tuple[str, bool]] = []   # (local name, is default) named after their declaration
        self.generics = _type_parameters(root)
        for node in root.named_children:    # Imports first: uses above a late require() still count
            self.collect_imports(node)
        for node in root.named_children:
            self.visit(node, None, "", top=True)
        for name, default in self.exports:
            for symbol in self.out.symbols:
                if symbol.parent is None and symbol.name == name:
                    symbol.exported, symbol.default = True, symbol.default or default

    # -- Imports ---------------------------------------------------------------------------------

    def add_import(self, spec: str, node: Node, names: Optional[Dict[str, str]] = None) -> None:
        self.out.imports.append(ParsedImport(spec, node.start_point[0] + 1, names=names or {}))
        self.bindings.update(names or {})

    def collect_imports(self, node: Node) -> None:
        if node.type == "import_statement":
            source = _string(node.child_by_field_name("source"))
            names: Dict[str, str] = {}
            clause = next((c for c in node.named_children if c.type == "import_clause"), None)
            for part in clause.named_children if clause is not None else []:
                if part.type == "identifier":
                    names[_text(part)] = "default"
                elif part.type == "namespace_import":
                    names[_text(part.named_children[0])] = "*"
                elif part.type == "named_imports":
                    for spec in part.named_children:
                        imported = _text(spec.child_by_field_name("name"))
                        names[_text(spec.child_by_field_name("alias")) or imported] = imported
            if source is not None:
                self.add_import(source, node, names)
        elif node.type == "export_statement" and node.child_by_field_name("source") is not None:
            self.add_import(_string(node.child_by_field_name("source")) or "", node)   # export … from "./x"
        elif node.type in ("lexical_declaration", "variable_declaration"):
            for declarator in node.named_children:
                if declarator.type == "variable_declarator":
                    self.require(declarator)
        elif node.type == "export_statement":
            declaration = node.child_by_field_name("declaration")
            if declaration is not None:
                self.collect_imports(declaration)

    def require(self, declarator: Node) -> bool:
        """const x = require("m"), const {a, b: c} = require("m"), const y = require("m").y"""
        value, member = declarator.child_by_field_name("value"), None
        if value is not None and value.type == "member_expression":
            value, member = value.child_by_field_name("object"), _text(value.child_by_field_name("property"))
        spec = self.required_module(value)
        if spec is None:
            return False
        target = declarator.child_by_field_name("name")
        names: Dict[str, str] = {}
        if target.type == "identifier":
            names[_text(target)] = member or "*"
        elif target.type == "object_pattern":
            for item in target.named_children:
                if item.type == "shorthand_property_identifier_pattern":
                    names[_text(item)] = _text(item)
                elif item.type == "pair_pattern" and item.child_by_field_name("value").type == "identifier":
                    names[_text(item.child_by_field_name("value"))] = _text(item.child_by_field_name("key"))
        self.add_import(spec, declarator, names)
        return True

    @staticmethod
    def required_module(node: Optional[Node]) -> Optional[str]:
        if node is None or node.type != "call_expression":
            return None
        function, arguments = node.child_by_field_name("function"), node.child_by_field_name("arguments")
        if function.type not in ("identifier", "import") or _text(function) not in ("require", "import"):
            return None
        return _string(arguments.named_children[0]) if arguments is not None and arguments.named_child_count else None

    # -- Declarations and references -------------------------------------------------------------

    def visit(self, node: Node, scope: Optional[int], container: str, top: bool = False,
              exported: bool = False, default: bool = False) -> None:
        kind = node.type
        if kind == "import_statement":
            return
        if kind == "export_statement":
            return self.export(node, scope, container, top)
        if kind in ("function_declaration", "generator_function_declaration", "function_signature"):
            name = _text(node.child_by_field_name("name")) or "default"
            index = self.function(node, "function", name, scope, container, exported, default)
            return self.children(node, index, self.qualify(container, name), skip=("name",))
        if kind in _SCRIPT_TYPES and (kind != "class" or top):
            return self.type_declaration(node, scope, container, exported, default)
        if kind in ("lexical_declaration", "variable_declaration") and top:
            for declarator in node.named_children:
                if declarator.type == "variable_declarator":
                    self.variable(declarator, scope, container, exported)
            return
        if kind == "expression_statement" and top and self.commonjs_export(node, scope):
            return
        if kind == "call_expression":
            self.call(node, scope)
            # The called name is recorded by the call itself; what it's reached through (a nested
            # call, say) and the arguments are visited as usual
            function = node.child_by_field_name("function")
            base = function.child_by_field_name("object") if function.type == "member_expression" else None
            if base is not None and base.type != "identifier":
                self.visit(base, scope, container)
            elif function.type not in ("identifier", "member_expression", "import"):
                self.visit(function, scope, container)
            return self.children(node, scope, container, skip=("function",))
        elif kind == "new_expression":
            name, receiver = self.callee(node.child_by_field_name("constructor"))
            arguments = node.child_by_field_name("arguments")
            self.ref("new", name, node, scope, receiver, arguments.named_child_count if arguments is not None else 0)
            return self.children(node, scope, container, skip=("constructor",))
        elif kind in ("jsx_opening_element", "jsx_self_closing_element"):
            name, receiver = self.callee(node.child_by_field_name("name"))
            if name[:1].isupper() or receiver:   # Lower-case names are HTML elements
                self.ref("jsx", name, node, scope, receiver)
            return self.children(node, scope, container, skip=("name",))
        elif kind == "jsx_closing_element":
            return
        elif kind == "type_identifier":
            return self.ref("type", _text(node), node, scope) if _text(node) not in self.generics else None
        elif kind == "identifier":
            if _text(node) in self.bindings:
                self.ref("use", _text(node), node, scope)
            return
        elif kind == "shorthand_property_identifier":
            if _text(node) in self.bindings:
                self.ref("use", _text(node), node, scope)
            return
        self.children(node, scope, container)

    def children(self, node: Node, scope: Optional[int], container: str, skip: Tuple[str, ...] = ()) -> None:
        skipped = {node.child_by_field_name(name) for name in skip}
        for child in node.named_children:
            if child not in skipped:
                self.visit(child, scope, container)

    @staticmethod
    def qualify(container: str, name: str, member: bool = False) -> str:
        return f"{container}{'#' if member else '.'}{name}" if container else name

    def function(self, node: Node, kind: str, name: str, scope: Optional[int], container: str,
                 exported: bool = False, default: bool = False, member: bool = False,
                 function_node: Optional[Node] = None) -> int:
        function_node = function_node or node
        parameters = function_node.child_by_field_name("parameters")
        params = parameters.named_child_count if parameters is not None else (
            1 if function_node.child_by_field_name("parameter") is not None else 0)
        return self.symbol(kind, name, self.qualify(container, name, member), scope, node,
                           function_node.child_by_field_name("body"), params=params, exported=exported, default=default)

    def export(self, node: Node, scope: Optional[int], container: str, top: bool) -> None:
        default = any(c.type == "default" for c in node.children)
        declaration = node.child_by_field_name("declaration")
        if declaration is not None:
            return self.visit(declaration, scope, container, top=True, exported=True, default=default)
        value = node.child_by_field_name("value")
        if value is not None:   # export default <expression>
            if value.type == "identifier":
                self.exports.append((_text(value), True))
            elif value.type in _FUNCTIONS:
                index = self.function(node, "function", "default", scope, container, True, True, function_node=value)
                return self.children(value, index, "default")
            elif value.type == "class":
                return self.type_declaration(value, scope, container, True, True)
            elif value.type == "object":
                index = self.symbol("variable", "default", "default", scope, node, exported=True, default=True)
                return self.object_members(value, index, "default")
            return self.visit(value, scope, container)
        for child in node.named_children:   # export { a, b as c }
            if child.type == "export_clause":
                for spec in child.named_children:
                    self.exports.append((_text(spec.child_by_field_name("name")),
                                         _text(spec.child_by_field_name("alias")) == "default"))

    def commonjs_export(self, node: Node, scope: Optional[int]) -> bool:
        """module.exports = X, module.exports = {a, b}, exports.a = …, module.exports.a = …"""
        assignment = node.named_children[0] if node.named_child_count else None
        if assignment is None or assignment.type != "assignment_expression":
            return False
        left, right = assignment.child_by_field_name("left"), assignment.child_by_field_name("right")
        target = _text(left)
        if target == "module.exports":
            if right.type == "identifier":
                self.exports.append((_text(right), True))
            elif right.type == "object":
                for item in right.named_children:
                    if item.type == "shorthand_property_identifier":
                        self.exports.append((_text(item), False))
                index = self.symbol("variable", "default", "default", scope, node, exported=True, default=True)
                self.object_members(right, index, "default")
                return True
            elif right.type in _FUNCTIONS:
                index = self.function(node, "function", "default", scope, "", True, True, function_node=right)
                self.children(right, index, "default")
                return True
            elif right.type == "class":
                self.type_declaration(right, scope, "", True, True)
                return True
        elif re.fullmatch(r"(?:module\.)?exports\.\w+", target):
            name = target.rsplit(".", 1)[1]
            if right.type in _FUNCTIONS:
                index = self.function(node, "function", name, scope, "", True, function_node=right)
                self.children(right, index, name)
                return True
            if right.type == "identifier":
                self.exports.append((_text(right), False))
        return False

    def type_declaration(self, node: Node, scope: Optional[int], container: str, exported: bool, default: bool) -> None:
        name = _text(node.child_by_field_name("name")) or "default"
        body = node.child_by_field_name("body")
        qualified = self.qualify(container, name)
        index = self.symbol(_SCRIPT_TYPES[node.type], name, qualified, scope, node, body, exported=exported, default=default)
        for child in node.named_children:
            if child.type == "class_heritage":
                clauses = [c for c in child.named_children if c.type in ("extends_clause", "implements_clause")]
                if not clauses:   # JavaScript: the superclass expression sits directly in the heritage
                    self.supertype("extends", child.named_children[0], index, qualified)
                for clause in clauses:
                    kind = "extends" if clause.type == "extends_clause" else "implements"
                    for item in clause.named_children:
                        if item.type != "type_arguments":
                            self.supertype(kind, item, index, qualified)
                        else:
                            self.visit(item, index, qualified)
            elif child.type in ("extends_type_clause", "extends_clause"):   # interface A extends B
                for item in child.named_children:
                    self.supertype("extends", item, index, qualified)
            elif child.type in ("type_parameters", "decorator"):
                self.visit(child, index, qualified)
        if body is None:
            if node.type == "type_alias_declaration":
                self.children(node, index, qualified, skip=("name",))
            return
        for member in body.named_children:
            if member.type in ("method_definition", "method_signature", "abstract_method_signature"):
                member_name = _text(member.child_by_field_name("name"))
                kind = "constructor" if member_name == "constructor" else "method"
                method = self.function(member, kind, member_name, index, qualified, member=True)
                self.children(member, method, qualified, skip=("name",))
            elif member.type in ("field_definition", "public_field_definition"):
                member_name = _text(member.child_by_field_name("name") or member.child_by_field_name("property"))
                value = member.child_by_field_name("value")
                if value is not None and value.type in _FUNCTIONS:   # handler = () => {…}
                    method = self.function(member, "method", member_name, index, qualified, member=True, function_node=value)
                    self.children(value, method, qualified)
                else:
                    field_index = self.symbol("field", member_name, self.qualify(qualified, member_name, True), index, member, value)
                    self.children(member, field_index, qualified, skip=("name", "property"))
            elif member.type not in ("property_signature", "enum_assignment", "property_identifier"):
                self.visit(member, index, qualified)
            else:
                self.children(member, index, qualified, skip=("name",))

    def supertype(self, kind: str, node: Node, index: int, container: str) -> None:
        if node.type == "generic_type":
            node = node.child_by_field_name("name") or node.named_children[0]
        name, receiver = self.callee(node)
        if name:
            self.ref(kind, name, node, index, receiver)
        else:   # A mixin or other expression: its parts are ordinary references
            self.visit(node, index, container)

    def variable(self, declarator: Node, scope: Optional[int], container: str, exported: bool) -> None:
        target, value = declarator.child_by_field_name("name"), declarator.child_by_field_name("value")
        module = value.child_by_field_name("object") if value is not None and value.type == "member_expression" else value
        if self.required_module(module) is not None:   # An import (recorded already), not a declaration
            return
        if target.type != "identifier":   # Destructuring: no single symbol to name
            return self.children(declarator, scope, container, skip=("name",))
        name = _text(target)
        statement = declarator.parent
        if value is not None and value.type in _FUNCTIONS:
            index = self.function(statement, "function", name, scope, container, exported, function_node=value)
            return self.children(value, index, self.qualify(container, name))
        if value is not None and value.type == "class":
            return self.type_declaration(value, scope, container, exported, False) if value.child_by_field_name("name") \
                else self.children(value, self.symbol("class", name, self.qualify(container, name), scope, statement,
                                                      value.child_by_field_name("body"), exported=exported), name)
        index = self.symbol("variable", name, self.qualify(container, name), scope, statement, value, exported=exported)
        annotation = declarator.child_by_field_name("type")
        if annotation is not None:
            self.visit(annotation, index, container)
        if value is None:
            return
        if value.type == "object":   # const api = { getUser() {…}, list: () => {…} }
            return self.object_members(value, index, self.qualify(container, name))
        self.visit(value, index, container)

    def object_members(self, node: Node, index: int, container: str) -> None:
        for item in node.named_children:
            value = item.child_by_field_name("value") if item.type == "pair" else None
            if item.type == "method_definition":
                method = self.function(item, "method", _text(item.child_by_field_name("name")), index, container, member=True)
                self.children(item, method, container, skip=("name",))
            elif value is not None and value.type in _FUNCTIONS and item.child_by_field_name("key").type == "property_identifier":
                method = self.function(item, "method", _text(item.child_by_field_name("key")), index, container,
                                       member=True, function_node=value)
                self.children(value, method, container)
            else:
                self.visit(item, index, container)

    @staticmethod
    def callee(node: Optional[Node]) -> Tuple[str, str]:
        """(name, receiver) of what's called or constructed: f → ("f", ""), a.b.f → ("f", "a.b")."""
        if node is None:
            return "", ""
        if node.type in ("identifier", "type_identifier"):
            return _text(node), ""
        if node.type in ("member_expression", "nested_type_identifier", "nested_identifier"):
            target = node.child_by_field_name("property") or node.child_by_field_name("name") or node.named_children[-1]
            base = node.child_by_field_name("object") or node.child_by_field_name("module") or node.named_children[0]
            receiver = _text(base)
            simple = base.type in ("identifier", "this", "super", "member_expression", "nested_identifier") and len(receiver) <= 60
            return _text(target), receiver if simple and re.fullmatch(r"[\w$.]+", receiver) else ""
        return "", ""

    def call(self, node: Node, scope: Optional[int]) -> None:
        function, arguments = node.child_by_field_name("function"), node.child_by_field_name("arguments")
        name, receiver = self.callee(function)
        args = arguments.named_children if arguments is not None and arguments.type == "arguments" else []
        if function.type in ("identifier", "import") and name in ("require", "import", ""):
            spec = self.required_module(node)
            if spec is not None and not any(i.line == node.start_point[0] + 1 and i.spec == spec for i in self.out.imports):
                self.add_import(spec, node)   # A bare require("x") or a dynamic import("x")
            return
        if name:
            self.ref("call", name, function, scope, receiver, len(args))
        self.http(name, receiver, args, node, scope)

    def http(self, name: str, receiver: str, args: List[Node], node: Node, scope: Optional[int]) -> None:
        """Routes the code serves (Express-style) and requests it makes (fetch, axios, $.ajax, an http client)."""
        if not args:
            return
        first = args[0]
        path = _string(first)
        base = receiver.rsplit(".", 1)[-1]
        if name == "fetch" and not receiver and _looks_like_path(path):
            return self.endpoint("client", self.option(args[1:], "method") or "GET", path, node, scope, "fetch")
        if first.type == "object" and (name in ("axios", "ajax", "request") or base in ("axios", "$", "jQuery")):
            url = self.option(args, "url", as_path=True)   # axios({url, method}), $.ajax({url, type})
            if _looks_like_path(url):
                method = self.option(args, "method") or self.option(args, "type") or "GET"
                self.endpoint("client", method, url, node, scope, "ajax" if base in ("$", "jQuery") else "axios")
            return
        if name.lower() in HTTP_METHODS and receiver and _looks_like_path(path):
            method = HTTP_METHODS[name.lower()]
            handler = len(args) > 1 and args[-1].type in (*_FUNCTIONS, "identifier", "member_expression")
            if handler and _SERVER_RECEIVER.search(base) and path.startswith("/"):
                return self.endpoint("server", method, path, node, scope, "express")
            framework = "axios" if "axios" in receiver else "ajax" if base in ("$", "jQuery") else "http"
            self.endpoint("client", method, path, node, scope, framework)
        elif name in ("all", "use", "route") and receiver and _SERVER_RECEIVER.search(base) and path and path.startswith("/") \
                and name != "use":
            self.endpoint("server", "ANY", path, node, scope, "express")

    @staticmethod
    def option(args: List[Node], key: str, as_path: bool = False) -> Optional[str]:
        """A string option from an options object among the arguments: {method: "POST"} → "POST"."""
        for arg in args:
            if arg.type != "object":
                continue
            for pair in arg.named_children:
                if pair.type == "pair" and _text(pair.child_by_field_name("key")).strip("'\"") == key:
                    value = _string(pair.child_by_field_name("value"))
                    if value is not None:
                        return value if as_path else value.upper()
        return None
