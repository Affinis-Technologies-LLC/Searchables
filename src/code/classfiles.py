"""
Reads the public API of Java class files (ADR-017) without a JVM: per class its name, kind,
supertypes and type parameters; per public or protected member its name, kind, parameter count,
erased type, and (from the generic Signature attribute) whether it returns or carries a type
variable. Jars, jmods and class folders are read where they are; nothing is run.

The class file format: magic, versions, a constant pool, access flags, this/super class, interfaces,
fields, methods, attributes. Only the constant pool's UTF-8 and Class entries are needed here.
"""
import os
import re
import struct
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

ACC_PUBLIC, ACC_PRIVATE, ACC_PROTECTED, ACC_STATIC = 0x0001, 0x0002, 0x0004, 0x0008
ACC_INTERFACE, ACC_ANNOTATION, ACC_ENUM, ACC_SYNTHETIC = 0x0200, 0x2000, 0x4000, 0x1000


@dataclass
class MemberInfo:
    name: str
    kind: str                   # method, constructor, field
    params: int
    returns: str                # Erased class name ("java.util.Optional"), "" for void/primitive, "$T" for the class's first type variable
    carried: str                # The first type argument of the return type: a class, "$T", or ""
    static: bool
    signature: str              # Readable: "Optional<T> findFirst()" / "PrintStream out"


@dataclass
class ClassInfo:
    qualified: str              # Dotted, with "$" for nested classes replaced by "."
    kind: str                   # class, interface, enum, annotation
    public: bool
    supers: List[str]           # Superclass (first) and interfaces, dotted
    type_params: List[str]
    members: List[MemberInfo] = field(default_factory=list)


def _dotted(internal: str) -> str:
    return internal.replace("/", ".").replace("$", ".")


def _class_of_descriptor(descriptor: str) -> str:
    """The erased class of a field descriptor or a method's return descriptor; "" for primitives, void and arrays."""
    if descriptor.startswith("L") and descriptor.endswith(";"):
        return _dotted(descriptor[1:-1])
    return ""


def _param_count(descriptor: str) -> int:
    inside = descriptor[1:descriptor.index(")")]
    count, i = 0, 0
    while i < len(inside):
        c = inside[i]
        while c == "[":
            i += 1
            c = inside[i]
        if c == "L":
            i = inside.index(";", i) + 1
        else:
            i += 1
        count += 1
    return count


def _signature_types(signature: str, type_params: Sequence[str]) -> Tuple[str, str]:
    """
    (returns, carried) from a generic signature's return part: "TT;" → ("$T", ""); "Ljava/util/Optional<TT;>;" →
    ("java.util.Optional", "$T"); "Ljava/util/List<Ljava/lang/String;>;" → ("java.util.List", "java.lang.String").
    Only the class's first type variable is tracked as "$T".
    """
    returns = signature[signature.index(")") + 1:] if ")" in signature else signature
    first = type_params[0] if type_params else None

    def one(text: str) -> str:
        if text.startswith("T") and text.endswith(";"):
            return "$T" if text[1:-1] == first else ""
        if text.startswith("L"):
            body = text[1:text.index("<")] if "<" in text else text[1:-1]
            return _dotted(body)
        return ""
    base = one(returns)
    carried = ""
    if "<" in returns:
        inner = returns[returns.index("<") + 1:]
        depth, start = 0, 0
        for i, c in enumerate(inner):
            if c == "<":
                depth += 1
            elif c == ">":
                if depth == 0:
                    break
                depth -= 1
            elif c == ";" and depth == 0:
                argument = inner[start:i + 1]
                carried = one(argument.lstrip("+-")) if argument.lstrip("+-") not in ("*",) else ""
                break
    return base, carried


def _class_type_params(signature: str) -> List[str]:
    if not signature.startswith("<"):
        return []
    names, depth, i = [], 0, 1
    start = 1
    while i < len(signature):
        c = signature[i]
        if c == "<":
            depth += 1
        elif c == ">":
            if depth == 0:
                break
            depth -= 1
        elif c == ":" and depth == 0 and start is not None:
            names.append(signature[start:i])
            start = None
        elif c == ";" and depth == 0:
            start = i + 1
        i += 1
    return [n for n in names if n]


def read_class(data: bytes) -> Optional[ClassInfo]:
    """The public API of one class file; None for synthetic or package-private classes, or a file that isn't one."""
    try:
        return _read_class(data)
    except (struct.error, IndexError, KeyError, ValueError, UnicodeDecodeError):
        return None


def _read_class(data: bytes) -> Optional[ClassInfo]:
    if data[:4] != b"\xca\xfe\xba\xbe":
        return None
    pos = 8
    count = struct.unpack_from(">H", data, pos)[0]
    pos += 2
    pool: Dict[int, object] = {}
    i = 1
    while i < count:
        tag = data[pos]
        pos += 1
        if tag == 1:
            length = struct.unpack_from(">H", data, pos)[0]
            pool[i] = data[pos + 2:pos + 2 + length].decode("utf-8", "replace")
            pos += 2 + length
        elif tag in (3, 4):
            pos += 4
        elif tag in (5, 6):
            pos += 8
            i += 1
        elif tag == 7:
            pool[i] = ("class", struct.unpack_from(">H", data, pos)[0])
            pos += 2
        elif tag == 8:
            pos += 2
        elif tag in (9, 10, 11, 12):
            pos += 4
        elif tag == 15:
            pos += 3
        elif tag == 16:
            pos += 2
        elif tag == 17 or tag == 18:
            pos += 4
        elif tag == 19 or tag == 20:
            pos += 2
        else:
            return None
        i += 1
    access, this_index, super_index = struct.unpack_from(">HHH", data, pos)
    pos += 6

    def class_name(index: int) -> str:
        entry = pool.get(index)
        return _dotted(str(pool.get(entry[1], ""))) if isinstance(entry, tuple) else ""
    if access & ACC_SYNTHETIC or not access & ACC_PUBLIC:
        return None
    qualified = class_name(this_index)
    supers = [class_name(super_index)] if super_index else []
    interfaces = struct.unpack_from(">H", data, pos)[0]
    pos += 2
    for _ in range(interfaces):
        supers.append(class_name(struct.unpack_from(">H", data, pos)[0]))
        pos += 2
    kind = "annotation" if access & ACC_ANNOTATION else "interface" if access & ACC_INTERFACE else "enum" if access & ACC_ENUM else "class"
    info = ClassInfo(qualified, kind, True, [s for s in supers if s and s != "java.lang.Object"], [])

    def attributes() -> Dict[str, bytes]:
        nonlocal pos
        n = struct.unpack_from(">H", data, pos)[0]
        pos += 2
        found = {}
        for _ in range(n):
            name_index, length = struct.unpack_from(">HI", data, pos)
            pos += 6
            found[str(pool.get(name_index, ""))] = data[pos:pos + length]
            pos += length
        return found

    members_raw: List[Tuple[int, str, str, Dict[str, bytes]]] = []
    for section in ("fields", "methods"):
        n = struct.unpack_from(">H", data, pos)[0]
        pos += 2
        for _ in range(n):
            flags, name_index, descriptor_index = struct.unpack_from(">HHH", data, pos)
            pos += 6
            members_raw.append((flags | (0x10000 if section == "methods" else 0), str(pool.get(name_index, "")),
                                str(pool.get(descriptor_index, "")), attributes()))
    class_attributes = attributes()
    class_signature = class_attributes.get("Signature")
    if class_signature:
        index = struct.unpack_from(">H", class_signature, 0)[0]
        info.type_params = _class_type_params(str(pool.get(index, "")))

    simple = qualified.rsplit(".", 1)[-1]
    for flags, name, descriptor, attrs in members_raw:
        if not flags & (ACC_PUBLIC | ACC_PROTECTED) or flags & ACC_SYNTHETIC or name in ("<clinit>",):
            continue
        is_method = bool(flags & 0x10000)
        signature_text = ""
        if "Signature" in attrs:
            signature_text = str(pool.get(struct.unpack_from(">H", attrs["Signature"], 0)[0], ""))
        if is_method:
            returns_descriptor = descriptor[descriptor.index(")") + 1:]
            returns, carried = (_signature_types(signature_text, info.type_params) if signature_text
                                else (_class_of_descriptor(returns_descriptor), ""))
            params = _param_count(descriptor)
            if name == "<init>":
                info.members.append(MemberInfo(simple, "constructor", params, qualified, "", False, f"{simple}({params} args)"))
            else:
                shown = (returns.rsplit(".", 1)[-1] if returns and returns != "$T" else info.type_params[0] if returns == "$T" else
                         _primitive(returns_descriptor))
                info.members.append(MemberInfo(name, "method", params, returns, carried, bool(flags & ACC_STATIC),
                                               f"{shown} {name}({params} args)".strip()))
        else:
            returns, carried = (_signature_types(signature_text, info.type_params) if signature_text else (_class_of_descriptor(descriptor), ""))
            shown = returns.rsplit(".", 1)[-1] if returns and returns != "$T" else info.type_params[0] if returns == "$T" else _primitive(descriptor)
            info.members.append(MemberInfo(name, "field", -1, returns, carried, bool(flags & ACC_STATIC), f"{shown} {name}".strip()))
    return info


_PRIMITIVES = {"V": "void", "I": "int", "J": "long", "Z": "boolean", "D": "double", "F": "float", "B": "byte", "C": "char", "S": "short"}


def _primitive(descriptor: str) -> str:
    if descriptor.startswith("["):
        return _primitive(descriptor[1:]) + "[]"
    if descriptor.startswith("L"):
        return _dotted(descriptor[1:-1]).rsplit(".", 1)[-1]
    return _PRIMITIVES.get(descriptor, "")


def read_archive(path: Path) -> Iterator[ClassInfo]:
    """Every public class in a jar or jmod (module-info and nested classes' synthetic parts skipped)."""
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.endswith(".class") or name.endswith("module-info.class") or name.endswith("package-info.class"):
                continue
            base = name.rsplit("/", 1)[-1][:-6]
            if re.fullmatch(r".*\$\d+", base):   # Anonymous classes
                continue
            info = read_class(archive.read(name))
            if info is not None:
                yield info


# ---- Where libraries are ----------------------------------------------------------------------------

def jdk_home() -> Optional[Path]:
    """A JDK with jmods, from SEARCHABLES_JAVA_HOME, JAVA_HOME, or the usual install folders; the newest wins."""
    candidates: List[Path] = []
    for variable in ("SEARCHABLES_JAVA_HOME", "JAVA_HOME"):
        value = os.environ.get(variable)
        if value:
            candidates.append(Path(value))
    home = Path.home()
    roots = [Path("/Library/Java/JavaVirtualMachines"), Path("/usr/lib/jvm"), Path("/opt/homebrew/opt"), Path("/usr/local/opt"),
             home / ".jdks", home / ".sdkman/candidates/java", Path("C:/Program Files/Java"), Path("C:/Program Files/Eclipse Adoptium"),
             Path("C:/Program Files/Microsoft"), Path("C:/Program Files/Amazon Corretto"), Path("C:/Program Files/Zulu")]
    for root in roots:
        if root.is_dir():
            for child in sorted(root.iterdir()):
                candidates += [child, child / "Contents" / "Home", child / "libexec" / "openjdk.jdk" / "Contents" / "Home"]
    with_jmods = [c for c in candidates if (c / "jmods" / "java.base.jmod").is_file()]
    if not with_jmods:
        return None
    return max(with_jmods, key=lambda c: (_jdk_version(c), str(c)))


def _jdk_version(home: Path) -> Tuple[int, ...]:
    try:
        text = (home / "release").read_text(errors="replace")
        match = re.search(r'JAVA_VERSION="([\d.]+)', text)
        if match:
            return tuple(int(p) for p in match.group(1).split(".") if p.isdigit())
    except OSError:
        pass
    return (0,)


def jdk_archives(home: Optional[Path]) -> List[Path]:
    """The JDK modules worth reading: java.base and a few commonly used ones."""
    if home is None:
        return []
    return [p for p in (home / "jmods" / f"{m}.jmod" for m in ("java.base", "java.sql", "java.net.http", "java.logging", "java.xml")) if p.is_file()]


def maven_repository() -> Path:
    return Path(os.environ.get("SEARCHABLES_MAVEN_REPO", Path.home() / ".m2" / "repository"))


def gradle_cache() -> Path:
    return Path(os.environ.get("SEARCHABLES_GRADLE_CACHE", Path.home() / ".gradle" / "caches" / "modules-2" / "files-2.1"))


def find_jar(group: str, artifact: str, version: str) -> Optional[Path]:
    """A declared dependency's jar in the local Maven repository or Gradle cache; None when it isn't there."""
    if not group or not artifact or not version or any(c in version for c in "${}[]"):
        return None
    maven = maven_repository() / Path(*group.split(".")) / artifact / version / f"{artifact}-{version}.jar"
    if maven.is_file():
        return maven
    gradle = gradle_cache() / group / artifact / version
    if gradle.is_dir():
        for hashed in gradle.iterdir():
            jar = hashed / f"{artifact}-{version}.jar"
            if jar.is_file():
                return jar
    return None
