"""
Reads Angular templates as code. A template refers to the components it places (by their
selectors), binds their inputs and outputs, and calls and reads the members of its own component in
expressions. None of that is in the TypeScript the parser reads, so templates are read here, from
the template file or the inline `template` string, after the components are known.
"""
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Set, Tuple

_TAG = re.compile(r"<([a-zA-Z][\w-]*)((?:\s+[^<>]*?)?)/?>", re.DOTALL)
# [prop]="expr", (event)="expr", *ngIf="expr", *ngFor="let x of expr", [(ngModel)]="expr"
_BINDING = re.compile(r"""(\[\(?[\w.$-]+\)?\]|\([\w.$-]+\)|\*ng\w+|\[attr\.[\w-]+\])\s*=\s*"([^"]*)\"""")
_INTERPOLATION = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
_IDENTIFIER = re.compile(r"(?<![\w$.'\"])([A-Za-z_$][\w$]*)\s*(\()?")
_KEYWORDS = {"let", "of", "as", "true", "false", "null", "undefined", "async", "typeof", "in", "trackBy", "index",
             "even", "odd", "first", "last", "else", "then", "ngIf", "ngFor", "ngSwitch", "ngClass", "ngStyle", "ngModel"}


@dataclass(frozen=True)
class TemplateRef:
    kind: str                   # jsx (a component placed), use (a member read), call (a member called), binding
    name: str
    line: int                   # Within the template text, from 1
    col: int
    component: str = ""         # For jsx and binding: the selector matched
    args: int = -1


def _position(text: str, offset: int) -> Tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    return line, offset - (text.rfind("\n", 0, offset) + 1) + 1


def _expression_refs(text: str, expression: str, start: int, locals_: Set[str]) -> Iterable[TemplateRef]:
    """Members of the host component used in an expression; template locals and pipes are left out."""
    for match in _IDENTIFIER.finditer(expression):
        name, called = match.group(1), bool(match.group(2))
        before = expression[:match.start()].rstrip()
        if name in _KEYWORDS or name in locals_ or name == "$event" or before.endswith("|"):
            continue
        line, col = _position(text, start + match.start())
        args = -1
        if called:
            rest = expression[match.end():]
            inner = rest[:rest.find(")")] if ")" in rest else rest
            args = 0 if not inner.strip() else inner.count(",") + 1
        yield TemplateRef("call" if called else "use", name, line, col, args=args)


def read_template(text: str, selectors: Dict[str, str]) -> List[TemplateRef]:
    """
    References in a template: `selectors` maps a selector ("app-user-list") to the component's name.
    Bindings on a placed component refer to its inputs and outputs; expressions refer to the host's members.
    """
    found: List[TemplateRef] = []
    locals_: Set[str] = set()
    for match in re.finditer(r"\*ngFor\s*=\s*\"\s*let\s+([\w$]+)", text):   # Template-local names
        locals_.add(match.group(1))
    for match in re.finditer(r"let-([\w$]+)|#([\w$]+)", text):
        locals_.add(match.group(1) or match.group(2))

    for tag in _TAG.finditer(text):
        name, attributes = tag.group(1), tag.group(2)
        selector = name.lower()
        component = selectors.get(selector, "")
        if component:
            line, col = _position(text, tag.start(1))
            found.append(TemplateRef("jsx", component, line, col, component=selector))
        for binding in _BINDING.finditer(attributes):
            key, expression = binding.group(1), binding.group(2)
            if component and key[0] in "[(":
                bound = key.strip("[]()")
                if not bound.startswith(("attr.", "class.", "style.")):
                    line, col = _position(text, tag.start(2) + binding.start(1))
                    found.append(TemplateRef("binding", bound, line, col, component=selector))
            expression_start = tag.start(2) + binding.start(2)
            if key.startswith("*ngFor"):
                expression = re.sub(r"^\s*let\s+[\w$]+\s+of", "", expression)   # The list, not the local
                expression_start += len(binding.group(2)) - len(expression)
            found.extend(_expression_refs(text, expression, expression_start, locals_))
    for match in _INTERPOLATION.finditer(text):
        found.extend(_expression_refs(text, match.group(1), match.start(1), locals_))
    return found
