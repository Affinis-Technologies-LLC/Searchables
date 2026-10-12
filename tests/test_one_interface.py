"""One interface (ADR-027): nothing imports the removed Streamlit interface's packages."""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
FORBIDDEN = ("streamlit", "pandas")


def test_nothing_imports_streamlit_or_pandas():
    offenders = []
    for path in [*(ROOT / "src").rglob("*.py"), *(ROOT / "tests").rglob("*.py"), *ROOT.glob("*.py")]:
        if ".venv" in path.parts or path.is_relative_to(ROOT / "src" / "ui"):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(r"\s*(from|import)\s+(" + "|".join(FORBIDDEN) + r")\b", line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert offenders == [], "\n".join(offenders)


def test_the_streamlit_interface_is_gone():
    assert not (ROOT / "app.py").exists() and not (ROOT / "src" / "ui").exists() and not (ROOT / ".streamlit").exists()
    requirements = (ROOT / "requirements.txt").read_text()
    assert "streamlit" not in requirements and "pandas" not in requirements
