"""Reads declared libraries from build files: package.json, pom.xml, build.gradle(.kts); and import aliases from tsconfig.json."""
import json
import re
import xml.etree.ElementTree as ElementTree
from typing import Dict, List, Optional, Tuple

MANIFESTS = ("package.json", "pom.xml", "build.gradle", "build.gradle.kts")
SCRIPT_CONFIGS = ("tsconfig.json", "jsconfig.json")

# (ecosystem, name, version, scope)
Declared = Tuple[str, str, str, str]

_NPM_SECTIONS = {"dependencies": "runtime", "devDependencies": "dev", "peerDependencies": "peer",
                 "optionalDependencies": "optional"}
# implementation("group:artifact:version"), testImplementation 'group:artifact:version'
_GRADLE_COORDINATE = re.compile(r"""\b(\w+)\s*\(?\s*['"]([\w.-]+):([\w.-]+)(?::([^'"@]+))?(?:@\w+)?['"]""")
# implementation group: 'g', name: 'a', version: 'v'
_GRADLE_MAP = re.compile(r"""\b(\w+)\s*\(?\s*group\s*[:=]\s*['"]([\w.-]+)['"]\s*,\s*name\s*[:=]\s*['"]([\w.-]+)['"]"""
                         r"""(?:\s*,\s*version\s*[:=]\s*['"]([^'"]+)['"])?""")
_GRADLE_CONFIGURATIONS = re.compile(r"(?i)^(?:api|compile|implementation|runtime|annotationProcessor|kapt"
                                    r"|\w*(?:Api|Compile|CompileOnly|Implementation|Runtime|RuntimeOnly))$|Only$")


def read_manifest(name: str, text: str) -> List[Declared]:
    """The libraries a build file declares; an unreadable file declares none."""
    try:
        if name == "package.json":
            return _npm(text)
        if name == "pom.xml":
            return _maven(text)
        return _gradle(text)
    except (ValueError, ElementTree.ParseError):
        return []


def _npm(text: str) -> List[Declared]:
    data = json.loads(text)
    return [("npm", name, str(version), scope)
            for section, scope in _NPM_SECTIONS.items()
            for name, version in (data.get(section) or {}).items()]


def _maven(text: str) -> List[Declared]:
    root = ElementTree.fromstring(text)
    found: List[Declared] = []

    def local(element) -> str:
        return element.tag.rsplit("}", 1)[-1]

    def walk(element, managed: bool) -> None:
        for child in element:
            tag = local(child)
            if tag == "dependency" and not managed:
                values = {local(part): (part.text or "").strip() for part in child}
                if values.get("groupId") and values.get("artifactId"):
                    found.append(("maven", f"{values['groupId']}:{values['artifactId']}", values.get("version", ""),
                                  values.get("scope", "compile")))
            elif tag not in ("build", "reporting"):   # Plugins' own dependencies aren't the project's
                walk(child, managed or tag == "dependencyManagement")
    walk(root, False)
    return found


def _gradle(text: str) -> List[Declared]:
    text = re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.DOTALL)
    found = []
    for pattern in (_GRADLE_COORDINATE, _GRADLE_MAP):
        for configuration, group, artifact, version in pattern.findall(text):
            if _GRADLE_CONFIGURATIONS.search(configuration):
                scope = "test" if configuration.lower().startswith("test") else configuration
                found.append(("gradle", f"{group}:{artifact}", version or "", scope))
    return list(dict.fromkeys(found))


def read_aliases(text: str) -> Optional[Tuple[str, Dict[str, List[str]]]]:
    """(baseUrl, paths) from a tsconfig/jsconfig: how non-relative imports such as "@/api/users" map to folders."""
    # These files allow comments and trailing commas, which JSON doesn't
    text = re.sub(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/', lambda m: m.group(1) or "", text, flags=re.DOTALL)
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    try:
        options = json.loads(text).get("compilerOptions") or {}
    except (ValueError, AttributeError):
        return None
    base, paths = options.get("baseUrl"), options.get("paths") or {}
    if base is None and not paths:
        return None
    return base or ".", {key: [v for v in values if isinstance(v, str)] for key, values in paths.items()
                         if isinstance(values, list)}
