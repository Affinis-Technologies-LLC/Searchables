"""
Builds a portable release (ADR-028): one archive per target that unpacks to a folder with its own
Python, the locked packages, the app, the meaning-search model and the deploy scripts. The target
machine installs nothing and downloads nothing.

    python deploy/build-release.py --target all            # win64, macos-arm64, macos-x86_64 into dist/
    python deploy/build-release.py --target win64 --out /tmp/releases

Network is used on the build machine only: GitHub (the Python build, WinSW), PyPI (wheels) and
the model's host (once; the project's models/ folder is reused when it has the pinned revision).
Nothing downloaded is run here: wheels are unpacked by pip into the bundle, the interpreter is
only copied. Hashes of everything fetched go into the bundle's RELEASE.md.
"""
import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src import config  # noqa: E402  (the model's name and pinned revision)

PYTHON_RELEASE = "20261009"           # python-build-standalone release (astral-sh/python-build-standalone)
PYTHON_VERSION = "3.11.17"
PYTHON_BASE = f"https://github.com/astral-sh/python-build-standalone/releases/download/{PYTHON_RELEASE}"
WINSW_VERSION = "v2.12.0"
WINSW_URL = f"https://github.com/winsw/winsw/releases/download/{WINSW_VERSION}/WinSW-x64.exe"


@dataclass(frozen=True)
class Target:
    name: str                   # win64, macos-arm64, macos-x86_64
    triple: str                 # python-build-standalone's platform triple
    pip_platform: str           # pip's --platform for the wheels
    deploy: str                 # deploy/windows or deploy/macos
    site_packages: str          # Inside python/
    archive: str                # zip or tar.gz

    @property
    def python_archive(self) -> str:
        return f"cpython-{PYTHON_VERSION}+{PYTHON_RELEASE}-{self.triple}-install_only_stripped.tar.gz"


TARGETS: Dict[str, Target] = {
    "win64": Target("win64", "x86_64-pc-windows-msvc", "win_amd64", "deploy/windows", "Lib/site-packages", "zip"),
    "macos-arm64": Target("macos-arm64", "aarch64-apple-darwin", "macosx_14_0_arm64", "deploy/macos", "lib/python3.11/site-packages", "tar.gz"),
    "macos-x86_64": Target("macos-x86_64", "x86_64-apple-darwin", "macosx_14_0_x86_64", "deploy/macos", "lib/python3.11/site-packages", "tar.gz"),
}

# What of the repository goes into a release: the app, never its tests, sources of the front end, data or history
INCLUDED_TOP = ("src", "docs/help", "VERSION", "README.md", "LICENSE", "requirements.txt", "requirements.lock", "APP_LAYOUT.md")
EXCLUDED_DIRS = {"__pycache__", "node_modules", ".git", "data", "models", "tests", "web", ".venv", "dist"}
EXCLUDED_SUFFIXES = (".pyc", ".pyo")


def version() -> str:
    return (ROOT / "VERSION").read_text().strip()


def commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def app_files(root: Path, target: Target) -> Iterator[Path]:
    """The repository files a release carries, relative to the root."""
    wanted = [*INCLUDED_TOP, target.deploy]
    for top in wanted:
        path = root / top
        if path.is_file():
            yield Path(top)
        elif path.is_dir():
            for file in sorted(path.rglob("*")):
                if not file.is_file():
                    continue
                relative = file.relative_to(root)
                if any(part in EXCLUDED_DIRS for part in relative.parts) or relative.suffix in EXCLUDED_SUFFIXES:
                    continue
                if relative.parts[:2] == ("src", "server") and relative.parts[2:3] == ("static",) and relative.name.endswith(".map"):
                    continue
                yield relative


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(url: str, into: Path, log) -> Path:
    into.mkdir(parents=True, exist_ok=True)
    path = into / url.rsplit("/", 1)[-1]
    if path.exists():
        return path
    log(f"downloading {url}")
    with urllib.request.urlopen(url, timeout=120) as response, path.open("wb") as out:
        shutil.copyfileobj(response, out)
    return path


def unpack_python(archive: Path, bundle: Path) -> None:
    """python-build-standalone's install_only archives hold one top folder, python/, which is the bundle's."""
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        if not all(m.name == "python" or m.name.startswith("python/") for m in members):
            raise ValueError(f"{archive.name} doesn't unpack to python/ only.")
        tar.extractall(bundle, filter="data")


def install_wheels(target: Target, bundle: Path, cache: Path, log) -> int:
    """The locked packages for the target, installed cross-platform into the bundle's site-packages: nothing of theirs runs."""
    site = bundle / "python" / target.site_packages
    site.mkdir(parents=True, exist_ok=True)
    log(f"installing requirements.lock for {target.pip_platform} into {site.relative_to(bundle)}")
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--require-hashes", "--only-binary=:all:",
                    "--platform", target.pip_platform, "--python-version", PYTHON_VERSION, "--implementation", "cp",
                    "--target", str(site), "--no-compile", "--cache-dir", str(cache / "pip"),
                    "-r", str(ROOT / "requirements.lock")], check=True)
    for junk in site.glob("bin"):   # Console scripts refer to the build machine's interpreter
        shutil.rmtree(junk, ignore_errors=True)
    return sum(1 for _ in site.glob("*.dist-info"))


def copy_app(target: Target, bundle: Path) -> int:
    count = 0
    for relative in app_files(ROOT, target):
        destination = bundle / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
        count += 1
    return count


def copy_model(bundle: Path, cache: Path, log) -> str:
    """The pinned model's snapshot as plain files (the cache's symlinks resolved), from the project's models/ or downloaded once."""
    name = "models--" + config.EMBEDDING_MODEL.replace("/", "--")
    revision = config.EMBEDDING_REVISION
    sources = [config.MODEL_DIR / name, cache / "models" / name]
    source = next((s for s in sources if (s / "snapshots" / revision).is_dir()), None)
    if source is None:
        log(f"downloading the model {config.EMBEDDING_MODEL}@{revision[:12]} (about 440 MB, once)")
        env = {**os.environ, "SEARCHABLES_MODEL_DIR": str(cache / "models")}
        subprocess.run([sys.executable, "-m", "src.search.semantic"], cwd=ROOT, env=env, check=True)
        source = cache / "models" / name
    snapshot = source / "snapshots" / revision
    destination = bundle / "models" / name / "snapshots" / revision
    destination.mkdir(parents=True, exist_ok=True)
    for file in sorted(snapshot.rglob("*")):
        if file.is_file() or file.is_symlink():
            relative = file.relative_to(snapshot)
            (destination / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file.resolve(), destination / relative)
    refs = bundle / "models" / name / "refs"
    refs.mkdir(exist_ok=True)
    (refs / "main").write_text(revision)
    return f"{config.EMBEDDING_MODEL}@{revision}"


def licence_entries(site: Path) -> List[dict]:
    """Name, version, licence and licence text of every installed distribution, from its metadata."""
    entries = []
    for info in sorted(site.glob("*.dist-info")):
        metadata = (info / "METADATA").read_text(encoding="utf-8", errors="replace") if (info / "METADATA").exists() else ""
        fields: Dict[str, List[str]] = {}
        for line in metadata.split("\n\n", 1)[0].splitlines():
            key, _, value = line.partition(":")
            fields.setdefault(key.strip().lower(), []).append(value.strip())
        licence = (fields.get("license-expression") or fields.get("license") or [""])[0]
        if not licence or len(licence) > 80:
            classifiers = [c.split("::")[-1].strip() for c in fields.get("classifier", []) if c.startswith("License")]
            licence = "; ".join(classifiers) or licence[:80]
        texts = []
        for file in sorted(info.rglob("*")):
            if file.is_file() and re.match(r"(?i)^(licen[cs]e|copying|notice)", file.name):
                texts.append(file.read_text(encoding="utf-8", errors="replace"))
        entries.append({"name": (fields.get("name") or [info.name.split("-")[0]])[0], "version": (fields.get("version") or [""])[0],
                        "licence": licence, "text": "\n\n".join(texts)})
    return entries


def licences_markdown(entries: List[dict], extras: List[dict]) -> str:
    lines = ["# Licences of what this release bundles", "",
             "Everything below is third-party, bundled unchanged" + (" (Searchables' own licence is in LICENSE)." if (ROOT / "LICENSE").exists() else "."), "",
             "| Component | Version | Licence |", "|---|---|---|"]
    for e in [*extras, *entries]:
        lines.append(f"| {e['name']} | {e['version']} | {e['licence']} |")
    lines += ["", "## Licence texts", ""]
    for e in [*extras, *entries]:
        if e.get("text"):
            lines += [f"### {e['name']} {e['version']}", "", "```", e["text"].strip(), "```", ""]
    return "\n".join(lines)


def front_end_licences() -> List[dict]:
    path = ROOT / "web" / "src" / "generated" / "licences.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return []
    items = data if isinstance(data, list) else data.get("licences", [])
    return [{"name": i.get("name", ""), "version": i.get("version", ""), "licence": i.get("licence") or i.get("license", ""), "text": i.get("text", "")}
            for i in items if isinstance(i, dict)]


def release_notes(target: Target, python_archive: Path, wheels: int, model: str, winsw: Optional[Path]) -> str:
    lines = [f"# Searchables {version()} — {target.name}", "",
             f"- Version: {version()}", f"- Commit: {commit()}", f"- Built: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
             f"- Target: {target.name} ({target.triple})", "",
             "## Bundled", "",
             f"- Python {PYTHON_VERSION} (python-build-standalone {PYTHON_RELEASE}): {python_archive.name}, SHA-256 {sha256_of(python_archive)}",
             f"- {wheels} Python packages from requirements.lock, installed for {target.pip_platform} (hashes as in the lock)",
             f"- Meaning-search model: {model}"]
    if winsw is not None:
        lines.append(f"- WinSW {WINSW_VERSION}: SHA-256 {sha256_of(winsw)}")
    lines += ["", "## Not bundled (optional, install on the machine)", "",
              "- Tesseract (OCR of scanned pages), git (the Git segment, blame and history), a browser.", "",
              "## Running", "",
              ("- `deploy\\windows\\run.ps1` to try it; `deploy\\windows\\install-service.ps1` for the service. See deploy\\windows\\README.md."
               if target.name == "win64" else
               "- `deploy/macos/run.sh` to try it; `deploy/macos/install-service.sh` for the background service. See deploy/macos/README.md."),
              "- The library (data/) is kept outside this folder; a new release unpacked beside the old one takes it over."]
    return "\n".join(lines) + "\n"


def pack(bundle: Path, out: Path, target: Target, log) -> Path:
    name = bundle.name
    if target.archive == "zip":
        archive = out / f"{name}.zip"
        log(f"writing {archive.name}")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for file in sorted(bundle.rglob("*")):
                if file.is_file():
                    zf.write(file, f"{name}/{file.relative_to(bundle).as_posix()}")
    else:
        archive = out / f"{name}.tar.gz"
        log(f"writing {archive.name}")
        with tarfile.open(archive, "w:gz", compresslevel=6) as tar:
            tar.add(bundle, arcname=name)
    return archive


def build(target: Target, out: Path, log=print, skip_model: bool = False) -> Path:
    cache = out / "cache"
    name = f"Searchables-{version()}-{target.name}"
    bundle = out / "build" / name
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True)
    log(f"== {name}")
    python_archive = fetch(f"{PYTHON_BASE}/{target.python_archive}", cache / "python", log)
    unpack_python(python_archive, bundle)
    wheels = install_wheels(target, bundle, cache, log)
    files = copy_app(target, bundle)
    log(f"copied {files} files of the app")
    model = copy_model(bundle, cache, log) if not skip_model else "not bundled (--skip-model)"
    winsw = None
    if target.name == "win64":
        winsw = fetch(WINSW_URL, cache / "winsw", log)
        shutil.copy2(winsw, bundle / "deploy" / "windows" / "WinSW-x64.exe")
    extras = [{"name": "CPython (python-build-standalone)", "version": f"{PYTHON_VERSION}+{PYTHON_RELEASE}", "licence": "PSF-2.0 (CPython); MPL-2.0 (build scripts)", "text": ""},
              {"name": config.EMBEDDING_MODEL, "version": config.EMBEDDING_REVISION[:12], "licence": "MIT", "text": ""},
              *([{"name": "WinSW", "version": WINSW_VERSION, "licence": "MIT", "text": ""}] if winsw else []),
              *front_end_licences()]
    (bundle / "LICENCES.md").write_text(licences_markdown(licence_entries(bundle / "python" / target.site_packages), extras), encoding="utf-8")
    (bundle / "RELEASE.md").write_text(release_notes(target, python_archive, wheels, model, winsw), encoding="utf-8")
    archive = pack(bundle, out, target, log)
    log(f"   {archive.name}: {archive.stat().st_size / 1e6:.0f} MB")
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a portable release of Searchables (ADR-028).")
    parser.add_argument("--target", choices=[*TARGETS, "all"], default="all")
    parser.add_argument("--out", default=str(ROOT / "dist"), help="Where the archives go (default: dist/)")
    parser.add_argument("--skip-model", action="store_true", help="Leave the model out (a smaller archive for a quick check)")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    targets = list(TARGETS.values()) if args.target == "all" else [TARGETS[args.target]]
    for target in targets:
        build(target, out, skip_model=args.skip_model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
