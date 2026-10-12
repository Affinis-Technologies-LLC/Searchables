"""The portable release's build (ADR-028): what goes in, what stays out, and the records it writes — without downloading anything."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
spec = importlib.util.spec_from_file_location("build_release", ROOT / "deploy" / "build-release.py")
build_release = importlib.util.module_from_spec(spec)
sys.modules["build_release"] = build_release
spec.loader.exec_module(build_release)


def test_the_app_files_carry_the_app_and_nothing_else():
    files = {str(p) for p in build_release.app_files(ROOT, build_release.TARGETS["win64"])}
    assert "VERSION" in files and "src/server/app.py" in files and "src/code/store.py" in files and "docs/help/code.md" in files
    assert "src/server/static/index.html" in files and "deploy/windows/install-service.ps1" in files and "requirements.lock" in files
    assert not any(f.startswith(("tests/", "web/", "data/", "models/", "dist/", ".git")) for f in files)
    assert not any("__pycache__" in f or f.endswith(".pyc") or f.startswith("deploy/macos") for f in files)
    mac = {str(p) for p in build_release.app_files(ROOT, build_release.TARGETS["macos-arm64"])}
    assert "deploy/macos/run.sh" in mac and not any(f.startswith("deploy/windows") for f in mac)


def test_targets_are_complete_and_pinned():
    for target in build_release.TARGETS.values():
        assert target.python_archive.startswith(f"cpython-{build_release.PYTHON_VERSION}+{build_release.PYTHON_RELEASE}-{target.triple}")
        assert target.archive in ("zip", "tar.gz") and target.site_packages and target.pip_platform
    assert build_release.TARGETS["win64"].site_packages == "Lib/site-packages"
    assert build_release.TARGETS["macos-arm64"].site_packages.startswith("lib/python3.11")


def test_licence_entries_read_metadata(tmp_path):
    info = tmp_path / "example-1.2.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: example\nVersion: 1.2\nLicense-Expression: MIT\nClassifier: License :: OSI Approved :: MIT License\n\nBody\n")
    (info / "LICENSE").write_text("Permission is hereby granted")
    entries = build_release.licence_entries(tmp_path)
    assert entries == [{"name": "example", "version": "1.2", "licence": "MIT", "text": "Permission is hereby granted"}]
    text = build_release.licences_markdown(entries, [{"name": "CPython", "version": "3.11", "licence": "PSF-2.0", "text": ""}])
    assert "| example | 1.2 | MIT |" in text and "| CPython | 3.11 | PSF-2.0 |" in text and "Permission is hereby granted" in text


def test_release_notes_name_the_version_commit_and_target(tmp_path):
    archive = tmp_path / "cpython.tar.gz"
    archive.write_bytes(b"x")
    notes = build_release.release_notes(build_release.TARGETS["macos-x86_64"], archive, 75, "intfloat/e5-base-v2@abc", None)
    assert f"Version: {build_release.version()}" in notes and "Target: macos-x86_64" in notes and "75 Python packages" in notes
    assert "WinSW" not in notes and "deploy/macos/run.sh" in notes
    windows = build_release.release_notes(build_release.TARGETS["win64"], archive, 75, "m", archive)
    assert "WinSW" in windows and "run.ps1" in windows


def test_the_scripts_know_a_bundle():
    assert 'python\\python.exe' in (ROOT / "deploy/windows/run.ps1").read_text() and 'python\\python.exe' in (ROOT / "deploy/windows/install-service.ps1").read_text()
    assert "python/bin/python3" in (ROOT / "deploy/macos/common.sh").read_text() and "com.apple.quarantine" in (ROOT / "deploy/macos/common.sh").read_text()
    assert "WinSW-x64.exe" in (ROOT / "deploy/windows/install-service.ps1").read_text()


def test_pymupdf_s_agpl_terms_are_named_in_the_licence_table():
    """ADR-029: the one copyleft component is shown as such, in this environment and in any bundle built here."""
    import sysconfig
    places = [Path(sysconfig.get_paths()["purelib"])]
    places += [p for p in (ROOT / "dist" / "build").glob("Searchables-*/python/*/site-packages")]
    places += [p for p in (ROOT / "dist" / "build").glob("Searchables-*/python/lib/python*/site-packages")]
    assert places
    for site in places:
        entries = {e["name"].lower(): e for e in build_release.licence_entries(site)}
        assert "pymupdf" in entries, f"PyMuPDF not installed in {site}"
        licence = entries["pymupdf"]["licence"]
        assert ("AGPL" in licence.upper() or "AFFERO" in licence.upper()) and "artifex" in licence.lower(), f"{site}: {licence!r}"
        others = [name for name, e in entries.items() if name != "pymupdf" and "GPL" in e["licence"].upper() and "LGPL" not in e["licence"].upper()]
        assert others == [], f"other copyleft components in {site}: {others}"   # A new one would reopen ADR-029
