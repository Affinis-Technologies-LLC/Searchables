"""Compares two editions of a standard clause by clause."""
import difflib
import html
import re
from collections import OrderedDict
from typing import Dict, List, Optional, Sequence, Tuple

from src.models import ClauseDiff, ClauseText, TextBlock

_SHALL = re.compile(r"\b(?:shall|must)\b", re.IGNORECASE)
_SHOULD = re.compile(r"\bshould\b", re.IGNORECASE)
_MAY = re.compile(r"\b(?:may|need not)\b")

TITLE_MATCH = 0.6       # Same number: titles at least this similar (by word) are the same clause
CONTENT_MATCH = 0.6     # Different number and title: text at least this similar is the same clause


def clause_texts(blocks: Sequence[TextBlock]) -> "OrderedDict[str, ClauseText]":
    """
    Groups a document's blocks by clause. The text is the clause's own content, not its
    sub-clauses', so a change is reported where it happened.
    """
    grouped: Dict[str, dict] = OrderedDict()
    for block in blocks:
        key = block.clause_num or block.clause_title
        if not key:
            continue  # Front matter before the first heading
        entry = grouped.setdefault(key, {"num": block.clause_num, "title": block.clause_title, "parts": [],
                                         "page": block.page, "bbox": block.bbox})
        if block.kind == "heading":
            entry["page"], entry["bbox"] = block.page, block.bbox
        else:
            entry["parts"].append(block.text)

    clauses: "OrderedDict[str, ClauseText]" = OrderedDict()
    for key, e in grouped.items():
        text = " ".join(e["parts"])
        clauses[key] = ClauseText(
            key=key, num=e["num"], title=e["title"], text=text, page=e["page"], bbox=e["bbox"],
            provisions=(len(_SHALL.findall(text)), len(_SHOULD.findall(text)), len(_MAY.findall(text))),
        )
    return clauses


def _ratio(a: str, b: str) -> float:
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a.split(), b.split(), autojunk=False).ratio()


def _normalize_title(title: str) -> str:
    return re.sub(r"\W+", " ", title.lower()).strip()


def compare(old_blocks: Sequence[TextBlock], new_blocks: Sequence[TextBlock]) -> List[ClauseDiff]:
    """
    Pairs clauses by identical title (when unique in both editions, so renumbered clauses are
    found before their old number is claimed by a new clause), then by number when the title or
    content still agrees, then by similar content alone. Unpaired clauses are added or removed.
    Results follow the new edition's order, with removed clauses after the clause they followed.
    """
    old, new = clause_texts(old_blocks), clause_texts(new_blocks)
    pairs: Dict[str, str] = {}  # new key → old key

    def by_title(clauses) -> Dict[str, List[str]]:
        index: Dict[str, List[str]] = {}
        for key, clause in clauses.items():
            if clause.title:
                index.setdefault(_normalize_title(clause.title), []).append(key)
        return index

    old_titles, new_titles = by_title(old), by_title(new)
    for title, new_keys in new_titles.items():
        # "General" and the like repeat under many clauses; only a title unique on both sides identifies one
        if len(new_keys) == 1 and len(old_titles.get(title, [])) == 1:
            pairs[new_keys[0]] = old_titles[title][0]

    for key, clause in new.items():
        if key in pairs or key not in old or key in pairs.values():
            continue
        same_title = _ratio(_normalize_title(old[key].title), _normalize_title(clause.title)) >= TITLE_MATCH
        if same_title or _ratio(old[key].text, clause.text) >= CONTENT_MATCH:
            pairs[key] = key

    unpaired_old = [k for k in old if k not in pairs.values()]
    for key, clause in new.items():
        if key in pairs or not clause.text:
            continue
        best: Tuple[float, Optional[str]] = (0.0, None)
        for old_key in unpaired_old:
            score = _ratio(old[old_key].text, clause.text)
            if score > best[0]:
                best = (score, old_key)
        if best[1] and best[0] >= CONTENT_MATCH:
            pairs[key] = best[1]
            unpaired_old.remove(best[1])

    diffs: List[ClauseDiff] = []
    matched_old = set(pairs.values())
    old_order = list(old)
    placed_removed = set()
    for key, clause in new.items():
        if key in pairs:
            old_clause = old[pairs[key]]
            similarity = _ratio(old_clause.text, clause.text)
            status = "unchanged" if old_clause.text == clause.text and old_clause.title == clause.title else "changed"
            diffs.append(ClauseDiff(status, old_clause, clause, similarity, renumbered=pairs[key] != key))
            # Removed clauses that followed this one in the old edition go here, keeping reading order
            for old_key in old_order[old_order.index(pairs[key]) + 1:]:
                if old_key in matched_old:
                    break
                if old_key not in placed_removed:
                    diffs.append(ClauseDiff("removed", old[old_key], None, 0.0))
                    placed_removed.add(old_key)
        else:
            diffs.append(ClauseDiff("added", None, clause, 0.0))
    for old_key in old_order:
        if old_key not in matched_old and old_key not in placed_removed:
            diffs.append(ClauseDiff("removed", old[old_key], None, 0.0))
    return diffs


def word_diff_html(old: str, new: str) -> str:
    """Inline word-level diff: deletions struck through, insertions underlined."""
    a, b = old.split(), new.split()
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(html.escape(" ".join(a[i1:i2])))
            continue
        if op in ("delete", "replace"):
            out.append(f'<del class="diff-del">{html.escape(" ".join(a[i1:i2]))}</del>')
        if op in ("insert", "replace"):
            out.append(f'<ins class="diff-ins">{html.escape(" ".join(b[j1:j2]))}</ins>')
    return " ".join(out)


def provision_change(diff: ClauseDiff) -> str:
    """ "shall 2→1, should 0→1" for the verbal forms whose counts changed; "" when none did."""
    before = diff.old.provisions if diff.old else (0, 0, 0)
    after = diff.new.provisions if diff.new else (0, 0, 0)
    return ", ".join(f"{word} {a}→{b}" for word, a, b in zip(("shall", "should", "may"), before, after) if a != b)


def to_markdown(old_title: str, new_title: str, diffs: Sequence[ClauseDiff]) -> str:
    counts = {s: sum(d.status == s for d in diffs) for s in ("changed", "added", "removed", "unchanged")}
    renumbered = sum(d.renumbered for d in diffs)
    lines = [f"# {old_title} → {new_title}", "",
             f"{counts['changed']} changed · {counts['added']} added · {counts['removed']} removed · "
             f"{renumbered} renumbered · {counts['unchanged']} unchanged", ""]
    for d in diffs:
        if d.status == "unchanged" and not d.renumbered:
            continue
        ref = d.new or d.old
        heading = f"{ref.num} {ref.title}".strip()
        if d.renumbered:
            heading += f" (was {d.old.num or d.old.title})"
        lines += [f"## {heading} — {d.status}", ""]
        if change := provision_change(d):
            lines += [f"**Provisions:** {change}", ""]
        if d.status == "changed":
            lines += [f"- **Before:** {d.old.text}", f"- **After:** {d.new.text}", ""]
        elif d.status in ("added", "removed"):
            lines += [f"> {ref.text}", ""]
    return "\n".join(lines)
