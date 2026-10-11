"""The web API, called as the browser front end calls it."""
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from src import config
from src.server import app as server

PASSWORD = "correct horse battery"
WRITE = {"X-Requested-With": "searchables"}


@pytest.fixture
def client(model, monkeypatch):
    config.AUTH_FILE.unlink(missing_ok=True)
    monkeypatch.setattr(server, "services", server.Services())    # Fresh sessions; the library is the tests' own
    return TestClient(server.create_app())


@pytest.fixture
def signed_in(client):
    assert client.post("/api/session/setup", json={"password": PASSWORD, "confirm": PASSWORD}, headers=WRITE).status_code == 200
    return client


def wait_for_jobs(client):
    deadline = time.time() + 60
    while client.get("/api/state").json()["jobs"]["active"]:
        assert time.time() < deadline, "indexing didn't finish"
        time.sleep(0.05)


def test_everything_needs_a_session(client):
    assert client.get("/api/session").json()["setup"] is True
    assert client.get("/api/state").status_code == 401
    assert client.get("/api/documents/1/file").status_code == 401
    assert client.post("/api/session/setup", json={"password": "short", "confirm": "short"}, headers=WRITE).status_code == 400
    assert client.post("/api/session/setup", json={"password": PASSWORD, "confirm": PASSWORD}).status_code == 403  # No header
    assert client.post("/api/session/setup", json={"password": PASSWORD, "confirm": PASSWORD}, headers=WRITE).status_code == 200
    assert client.get("/api/state").status_code == 200
    assert "httponly" in client.post("/api/session/login", json={"password": PASSWORD}, headers=WRITE).headers["set-cookie"].lower()

    client.post("/api/session/logout", headers=WRITE)
    assert client.get("/api/state").status_code == 401
    assert client.post("/api/session/login", json={"password": "wrong password"}, headers=WRITE).status_code == 401
    assert client.post("/api/session/setup", json={"password": PASSWORD, "confirm": PASSWORD}, headers=WRITE).status_code == 400


def test_sign_in_locks_after_repeated_failures(signed_in, monkeypatch):
    monkeypatch.setattr(config, "LOGIN_MAX_ATTEMPTS", 2)
    signed_in.post("/api/session/logout", headers=WRITE)
    for _ in range(2):
        assert signed_in.post("/api/session/login", json={"password": "wrong password"}, headers=WRITE).status_code == 401
    assert signed_in.post("/api/session/login", json={"password": PASSWORD}, headers=WRITE).status_code == 429


def test_documents_search_and_research(signed_in, standard_pdf, monkeypatch):
    monkeypatch.setattr(config, "MEANING_MIN_SIMILARITY", 0.3)
    client = signed_in
    before = {d["id"] for d in client.get("/api/state").json()["documents"]}
    upload = client.post("/api/documents?filename=API-STD-1.pdf", content=standard_pdf + b"\n% api", headers=WRITE)
    assert upload.status_code == 200
    wait_for_jobs(client)
    doc = next(d for d in client.get("/api/state").json()["documents"] if d["id"] not in before)
    assert (doc["title"], doc["page_count"], doc["meaning"]) == ("API-STD-1", 3, True)
    scope = f"&docs={doc['id']}"

    found = client.get("/api/search?q=how long must calibration records be kept" + scope).json()
    first = found["results"][0]
    assert first["block"]["text"].startswith("Calibration records shall be retained") and "<mark" in first["html"]
    assert first["block"]["provision"] == "requirement" and first["citation"].endswith("p. 1")
    assert client.get("/api/search?q=..." + scope).status_code == 400

    hits = client.get("/api/identifiers?q=k3.5" + scope).json()
    assert [h["group"] for h in hits["hits"]] == ["table", "rule"]
    assert hits["hits"][0]["table"]["rows"] == [["K3.5", "FLD 2041", "Item position update"]]

    page = client.get(f"/api/documents/{doc['id']}/pages/1?q=calibration records").json()
    assert page["hits"] and len(page["hits"][0]) == 4 and page["hit_pages"] == [1]
    assert any("<mark" in html for html in page["matches"].values())
    assert client.get(f"/api/documents/{doc['id']}/pages/9").status_code == 404
    table_page = client.get(f"/api/documents/{doc['id']}/pages/2?identifier=FLD 2041").json()
    table = next(iter(table_page["tables"].values()))
    assert table["columns"] == ["Message", "Field", "Purpose"] and len(table["rows"]) == 3
    assert any(r["target"] == "Table 1" for r in table_page["references"]) and table_page["hits"]

    outline = client.get(f"/api/documents/{doc['id']}/outline").json()
    assert [o["num"] for o in outline][:4] == ["1", "1.1", "2", "2.1"] and outline[1]["level"] == 2
    pdf = client.get(f"/api/documents/{doc['id']}/file")
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")

    related = client.get(f"/api/blocks/{first['block']['id']}/related").json()
    assert related["block"]["id"] == first["block"]["id"] and isinstance(related["groups"], list)

    # Pin it, add a note, export, unpin
    collection = client.get("/api/state").json()["collections"][0]["id"]
    assert client.post(f"/api/collections/{collection}/pins", json={"block_id": first["block"]["id"], "query": "q"},
                       headers=WRITE).json()["key"] == first["block"]["pin_key"]
    pinned = client.get(f"/api/collections/{collection}/pins").json()
    pin = next(p for p in pinned["pins"] if p["doc_id"] == doc["id"])
    assert first["block"]["pin_key"] in pinned["keys"] and pin["available"]
    client.patch(f"/api/pins/{pin['id']}", json={"note": "Check the period"}, headers=WRITE)
    exported = client.get(f"/api/collections/{collection}/export?format=md")
    assert "Check the period" in exported.text and "attachment" in exported.headers["content-disposition"]
    assert client.get(f"/api/collections/{collection}/export?format=docx").content[:2] == b"PK"
    client.delete(f"/api/collections/{collection}/pins?key={first['block']['pin_key']}", headers=WRITE)
    assert first["block"]["pin_key"] not in client.get(f"/api/collections/{collection}/pins").json()["keys"]

    # Library management
    families = client.get(f"/api/documents/{doc['id']}/identifiers").json()
    assert {f["family"] for f in families} >= {"K#.#", "FLD#"}
    changed = client.put(f"/api/documents/{doc['id']}/identifiers", json={"family": "FLD#", "enabled": True}, headers=WRITE).json()
    assert next(f for f in changed if f["family"] == "FLD#")["enabled"] is True
    assert client.patch(f"/api/documents/{doc['id']}", json={"title": "Renamed"}, headers=WRITE).json() == {"title": "Renamed"}
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 403                     # No header: refused
    assert client.delete(f"/api/documents/{doc['id']}", headers=WRITE).status_code == 200
    assert client.get(f"/api/documents/{doc['id']}/pages/1").status_code == 404


def test_compare_editions(signed_in):
    from conftest import make_pdf
    client = signed_in
    pages = lambda months: [["1 SCOPE", "1.1 Records", f"Calibration records shall be retained for a period of {months} months.",
                             "2 MARKING", "Each unit shall be marked with its serial number."]]
    before = {d["id"] for d in client.get("/api/state").json()["documents"]}
    for name, months in (("Edition 2019.pdf", 12), ("Edition 2024.pdf", 6)):
        client.post(f"/api/documents?filename={name}", content=make_pdf(pages(months)), headers=WRITE)
    wait_for_jobs(client)
    old, new = sorted((d for d in client.get("/api/state").json()["documents"] if d["id"] not in before), key=lambda d: d["title"])
    result = client.get(f"/api/compare?old={old['id']}&new={new['id']}").json()
    assert result["counts"]["changed"] == 1
    changed = next(d for d in result["diffs"] if d["status"] == "changed")
    assert changed["new"]["num"] == "1.1" and "<del" in changed["html"] and "<ins" in changed["html"]
    assert "1.1 Records" in client.get(f"/api/compare?old={old['id']}&new={new['id']}&format=md").text
    assert client.get(f"/api/compare?old={old['id']}&new={old['id']}").status_code == 400


def test_code_api(signed_in):
    client = signed_in
    for codebase in client.get("/api/state").json()["codebases"]:
        client.delete(f"/api/codebases/{codebase['id']}", headers=WRITE)
    assert client.post("/api/codebases", json={"root": "/no/such/folder"}, headers=WRITE).status_code == 400
    codebase = client.post("/api/codebases", json={"root": str(Path(__file__).parent / "codebase"), "name": "Demo"},
                           headers=WRITE).json()
    wait_for_jobs(client)
    base = f"/api/codebases/{codebase['id']}"
    assert client.get("/api/state").json()["codebases"][0]["symbol_count"] == 33
    assert len(client.get(base + "/files").json()) == 10

    fetch_user = next(s for s in client.get(base + "/symbols?q=fetchUser").json() if s["name"] == "fetchUser")
    usages = client.get(f"/api/code/symbols/{fetch_user['id']}/usages").json()
    assert [(u["path"].rsplit("/", 1)[-1], u["line"], u["certainty"]) for u in usages] == [("UserCard.tsx", 7, "resolved")]

    # Go to definition from where it's called, and what's declared under the cursor
    use = usages[0]
    at = client.get(f"/api/code/files/{use['file_id']}/at?line={use['line']}&col={use['col'] + 2}").json()
    assert at["target"]["id"] == fetch_user["id"] and at["ref"]["kind"] == "call"
    declared = client.get(f"/api/code/files/{fetch_user['file_id']}/at?line=5&col=25").json()
    assert declared["declared"]["id"] == fetch_user["id"] and declared["ref"] is None

    file = client.get(f"/api/code/files/{fetch_user['file_id']}").json()
    assert file["text"].startswith("import axios") and [s["name"] for s in file["outline"]][:2] == ["User", "fetchUser"]
    audit = next(s for s in client.get(base + "/symbols?q=audit").json())
    calls = client.get(f"/api/code/symbols/{audit['id']}/calls?direction=callers").json()
    assert calls["tree"][0]["symbol"]["name"] == "save" and calls["tree"][0]["children"]
    detail = client.get(f"/api/code/symbols/{calls['tree'][0]['symbol']['id']}").json()
    assert [s["qualified"] for s in detail["hierarchy"]["overrides"]] == ["com.acme.service.Repository#save"]

    # An unlinked call offers the declarations it may mean
    controller = next(f for f in client.get(base + "/files").json() if f["path"].endswith("UserController.java"))
    loose = client.get(f"/api/code/files/{controller['id']}/at?line=26&col=27").json()
    assert loose["target"] is None and {s["qualified"] for s in loose["candidates"]} >= {"com.acme.service.UserService#save"}

    dependencies = client.get(base + "/dependencies").json()
    assert {"axios", "junit:junit"} <= {d["name"] for d in dependencies["declared"]}
    assert client.get(base + "/package?name=axios").json()["members"] == [{"name": "axios#get", "uses": 1}, {"name": "axios#post", "uses": 1}]
    assert len(client.get(base + "/external?target=axios%23get").json()) == 1
    endpoints = client.get(base + "/endpoints").json()
    assert {(e["route"]["method"], e["route"]["path"], len(e["calls"])) for e in endpoints["served"]} >= {("POST", "/api/users", 1)}
    assert [h["line"] for h in client.get(base + "/text?q=PostMapping").json()] == [23]

    collection = client.get("/api/state").json()["collections"][0]["id"]
    client.post(f"/api/collections/{collection}/pins", json={"symbol_id": fetch_user["id"]}, headers=WRITE)
    pin = client.get(f"/api/collections/{collection}/pins").json()["pins"][-1]
    assert pin["kind"] == "code" and pin["text"].startswith("export async function fetchUser")


def test_catalogue_health_and_acronyms(signed_in):
    from conftest import MESSAGE_FOOTERS, make_pdf, message_standard
    client = signed_in
    before = {d["id"] for d in client.get("/api/state").json()["documents"]}
    for name, pages in (("XYZ-STD-8888A.pdf", message_standard()), ("XYZ-STD-8888B.pdf", message_standard(bits="21"))):
        client.post(f"/api/documents?filename={name}", content=make_pdf(pages, header="XYZ-STD-8888", footers=MESSAGE_FOOTERS) + name.encode(),
                    headers=WRITE)
    wait_for_jobs(client)
    old, new = sorted((d for d in client.get("/api/state").json()["documents"] if d["id"] not in before), key=lambda d: d["title"])
    assert old["distribution"].startswith("DISTRIBUTION STATEMENT C")
    for doc in (old, new):
        for family in ("GRP/ITM#/#", "GRP#", "M#.#", "M#.#I", "M#.#E#"):
            client.put(f"/api/documents/{doc['id']}/identifiers", json={"family": family, "enabled": True}, headers=WRITE)
    scope = f"docs={old['id']},{new['id']}"

    entries = {e["key"]: e for e in client.get(f"/api/catalogue?{scope}").json()}
    assert entries["M3.2I"]["parent"] == "M3.2" and entries["GRP/ITM281/001"]["parent"] == "GRP281"
    entry = client.get(f"/api/catalogue/entry?id=M3.2I&docs={old['id']}").json()
    assert entry["tables"][0]["rows"][0] == ["Reference Number", "281/001", "19"] and "GRP/ITM 281/001" in entry["contains"]
    assert entry["documents"] == [{"id": old["id"], "title": old["title"]}]
    changes = client.get(f"/api/catalogue/changes?id=M3.2I&old={old['id']}&new={new['id']}").json()
    assert [(c["old"][2], c["new"][2]) for c in changes["changed"]] == [["19", "21"]] or changes["changed"][0]["new"][2] == "21"

    health = {c["name"]: c for c in client.get(f"/api/documents/{old['id']}/health").json()}
    assert health["Printed page numbers"]["value"] == "100%" and health["Tables"]["value"] == "3"

    # An acronym in a search is spelled out for the meaning search; the glossary lists it
    found = client.get(f"/api/search?q=when is splr reported&docs={old['id']}").json()
    assert found["expanded"] == [{"acronym": "SPLR", "meaning": "Status, Position and Location Report"}]
    assert any(t["acronym"] and t["term"] == "RN" for t in client.get(f"/api/documents/{old['id']}/glossary").json())
    page = client.get(f"/api/documents/{old['id']}/pages/2").json()
    assert page["page_label"] == "5-1" and any(t["term"] == "RN" for t in page["terms"])
    marked = client.get(f"/api/documents/{old['id']}/pages/2?identifier=GRP/ITM 281/001").json()
    assert len(marked["hits"]) >= 2                              # "GRP 281/ITM 001" in the text, "281/001" in the table

    # A pin carries the document's distribution statement into the export
    collection = client.get("/api/state").json()["collections"][0]["id"]
    block = next(b for b in page["blocks"] if b["text"].startswith("The M3.2 message"))
    client.post(f"/api/collections/{collection}/pins", json={"block_id": block["id"]}, headers=WRITE)
    assert "DISTRIBUTION STATEMENT C" in client.get(f"/api/collections/{collection}/export?format=md").text


def test_editing_api(signed_in, tmp_path):
    """Saving, creating, renaming and deleting files through the API (ADR-011)."""
    import shutil
    client = signed_in
    shutil.copytree(Path(__file__).parent / "codebase", tmp_path / "project")
    codebase = client.post("/api/codebases", json={"root": str(tmp_path / "project"), "name": "Demo"}, headers=WRITE).json()
    wait_for_jobs(client)
    base = f"/api/codebases/{codebase['id']}"
    service = next(f for f in client.get(base + "/files").json() if f["path"].endswith("UserService.java"))
    opened = client.get(f"/api/code/files/{service['id']}").json()
    assert opened["file"]["sha256"] == service["sha256"] and opened["editable"] is True

    # A save returns the new file (with its hash) and outline
    text = opened["text"].replace("private void audit(String what)", "private void audit(String what, int level)") \
                         .replace('audit("save")', 'audit("save", 1)')
    saved = client.put(f"/api/code/files/{service['id']}", json={"text": text, "sha256": service["sha256"]}, headers=WRITE)
    assert saved.status_code == 200 and saved.json()["file"]["sha256"] != service["sha256"]
    assert any(s["name"] == "audit" and s["params"] == 2 for s in saved.json()["outline"])
    assert "int level" in (tmp_path / "project" / service["path"]).read_text()

    # A stale save is refused with the current text, so the editor can show the difference
    stale = client.put(f"/api/code/files/{service['id']}", json={"text": "x", "sha256": service["sha256"]}, headers=WRITE)
    assert stale.status_code == 409 and "int level" in stale.json()["current_text"] and stale.json()["current_sha256"] == saved.json()["file"]["sha256"]
    assert "int level" in (tmp_path / "project" / service["path"]).read_text()

    # Creating, renaming and deleting
    created = client.post(base + "/files", json={"path": "backend/src/main/java/com/acme/model/Role.java",
                                                  "text": "package com.acme.model;\npublic class Role {}\n"}, headers=WRITE)
    assert created.status_code == 200 and created.json()["file"]["language"] == "java"
    assert client.post(base + "/files", json={"path": "../outside.java"}, headers=WRITE).status_code == 400
    role = created.json()["file"]
    moved = client.post(f"/api/code/files/{role['id']}/rename", json={"path": "backend/src/main/java/com/acme/Role.java", "sha256": role["sha256"]}, headers=WRITE)
    assert moved.status_code == 200 and moved.json()["file"]["path"].endswith("acme/Role.java")
    assert client.request("DELETE", f"/api/code/files/{role['id']}", json={"sha256": "stale"}, headers=WRITE).status_code == 409
    assert client.request("DELETE", f"/api/code/files/{role['id']}", json={"sha256": moved.json()["file"]["sha256"]}, headers=WRITE).status_code == 200
    assert client.get(f"/api/code/files/{role['id']}").status_code == 404

    # Replacing in several files is previewed, then applied all or nothing
    preview = client.get(base + "/replace?q=audit&r=record").json()
    assert {c["path"].rsplit("/", 1)[-1] for c in preview["changes"]} == {"UserService.java"} and preview["changes"][0]["count"] == 2
    changes = [{"file_id": c["file_id"], "sha256": c["sha256"], "text": c["text"]} for c in preview["changes"]]
    applied = client.post(base + "/replace", json={"changes": changes}, headers=WRITE)
    assert applied.status_code == 200 and len(applied.json()["files"]) == 1
    assert [h["line"] for h in client.get(base + "/text?q=record").json()] == [18, 26]

    # Saving while a scan is running is refused
    client.post(base + "/scan", headers=WRITE)
    busy = client.put(f"/api/code/files/{service['id']}", json={"text": text, "sha256": "x"}, headers=WRITE)
    assert busy.status_code in (400, 409)
    wait_for_jobs(client)


def test_examples_api(signed_in):
    """Context, examples, completion and feedback for an unsaved buffer (ADR-012)."""
    client = signed_in
    codebase = client.post("/api/codebases", json={"root": str(Path(__file__).parent / "codebase_examples"), "name": "Shop"}, headers=WRITE).json()
    wait_for_jobs(client)
    service = next(f for f in client.get(f"/api/codebases/{codebase['id']}/files").json() if f["path"].endswith("OrderService.java"))
    text = client.get(f"/api/code/files/{service['id']}").json()["text"]
    marker = "    public List<Order> open() {\n"
    position = text.index(marker) + len(marker)
    typed = "        repository.find("
    buffer = text[:position] + typed + "\n" + text[position:]
    line = buffer.count("\n", 0, position) + 1
    body = {"text": buffer, "line": line, "col": len(typed) + 1}

    answer = client.post(f"/api/code/files/{service['id']}/context", json=body, headers=WRITE).json()
    assert answer["context"]["receiver_type"]["qualified"] == "com.shop.repo.OrderRepository"
    assert answer["filter"] == "same member on the same type" and answer["weights"]["T"] == 0.3
    first = answer["examples"][0]
    assert first["enclosing"] == "com.shop.service.OrderService#load" and first["features"]["T"] == 1.0 and first["lines"]
    assert client.post(f"/api/code/files/{service['id']}/context", json={"text": 5}, headers=WRITE).status_code == 400

    body["col"] = len("        repository.") + 1
    items = client.post(f"/api/code/files/{service['id']}/complete", json=body, headers=WRITE).json()["items"]
    assert {i["name"] for i in items} >= {"find", "save", "all", "count"} and next(i for i in items if i["name"] == "find")["examples"] == 3

    assert client.post("/api/code/feedback", json={"digest": answer["context"]["digest"], "ref_id": first["ref_id"], "action": "insert"}, headers=WRITE).status_code == 200
    assert client.post("/api/code/feedback", json={"digest": "x", "ref_id": 1, "action": "stole"}, headers=WRITE).status_code == 400


def test_session_state_and_about_carry_the_version(signed_in):
    from src import version
    client = signed_in
    session = client.get("/api/session").json()
    assert session["version"] == version.VERSION
    state = client.get("/api/state").json()
    assert state["version"] == version.VERSION and state["commit"] == version.describe()["commit"]
    about = client.get("/api/about").json()
    assert about["version"] == version.VERSION and about["python"].startswith("3.") and about["platform"]
    assert about["data_dir"] and about["model"]["name"] and isinstance(about["model"]["present"], bool)
    assert {"documents", "codebases", "collections", "pins"} <= set(about["counts"])
    assert any(p["name"].lower().startswith("starlette") for p in about["python_packages"]) and all("licence" in p for p in about["python_packages"])


def test_patterns_api(signed_in):
    client = signed_in
    root = str(Path(__file__).parent / "codebase_examples")
    codebase = next((c for c in client.get("/api/state").json()["codebases"] if c["root"] == root), None) \
        or client.post("/api/codebases", json={"root": root, "name": "Shop"}, headers=WRITE).json()   # Another test may have added it
    wait_for_jobs(client)
    patterns = client.get(f"/api/codebases/{codebase['id']}/patterns").json()
    assert {i["type_name"] for i in patterns["idioms"]} >= {"OrderRepository"} and patterns["layers"][0] == "com.shop.web"
    assert patterns["pairs"][0]["support"] >= 3 and patterns["entry_points"][0]["chain"][0]["symbol"].endswith("#load")


def test_impact_api(signed_in):
    client = signed_in
    root = str(Path(__file__).parent / "codebase_examples")
    codebase = next((c for c in client.get("/api/state").json()["codebases"] if c["root"] == root), None) \
        or client.post("/api/codebases", json={"root": root, "name": "Shop"}, headers=WRITE).json()
    wait_for_jobs(client)
    save = next(s for s in client.get(f"/api/codebases/{codebase['id']}/symbols?q=save").json() if s["qualified"].endswith("OrderRepository#save") and s["params"] == 1)
    impact = client.get(f"/api/code/symbols/{save['id']}/impact").json()
    assert [r["route"] for r in impact["routes"]] == ["POST /api/orders"] and len(impact["nodes"]) == 3


def test_unused_and_signature_api(signed_in):
    client = signed_in
    root = str(Path(__file__).parent / "codebase_examples")
    codebase = next((c for c in client.get("/api/state").json()["codebases"] if c["root"] == root), None) \
        or client.post("/api/codebases", json={"root": root, "name": "Shop"}, headers=WRITE).json()
    wait_for_jobs(client)
    unused = client.get(f"/api/codebases/{codebase['id']}/unused").json()
    assert any(u["symbol"]["qualified"].endswith("OrderService#open") for u in unused["methods"]) and unused["routes"] == []
    found = client.get(f"/api/codebases/{codebase['id']}/signatures?kind=method&returns=Optional&param=long").json()
    assert sorted(s["name"] for s in found) == ["find", "find"]


def test_snapshots_api(signed_in, tmp_path):
    import shutil
    client = signed_in
    shutil.copytree(Path(__file__).parent / "codebase_examples", tmp_path / "shop")
    codebase = client.post("/api/codebases", json={"root": str(tmp_path / "shop"), "name": "Snap"}, headers=WRITE).json()
    wait_for_jobs(client)
    snapshot = client.post(f"/api/codebases/{codebase['id']}/snapshots", json={"label": "before"}, headers=WRITE).json()
    assert snapshot["label"] == "before" and snapshot["symbol_count"] > 40
    service = tmp_path / "shop/backend/src/main/java/com/shop/service/OrderService.java"
    service.write_text(service.read_text().replace("public Order load(long id)", "public Order load(String id)"))
    client.post(f"/api/codebases/{codebase['id']}/scan", headers=WRITE)
    wait_for_jobs(client)
    diff = client.get(f"/api/codebases/{codebase['id']}/diff?against=snapshot:{snapshot['id']}").json()
    assert [c["now"]["name"] for c in diff["changed"]] == ["load"] and diff["changed"][0]["callers"][0]["from_name"].endswith("#get")
    assert client.get(f"/api/codebases/{codebase['id']}/diff?against=nothing").status_code == 400
    assert client.delete(f"/api/code/snapshots/{snapshot['id']}", headers=WRITE).status_code == 200
    assert client.get(f"/api/codebases/{codebase['id']}/snapshots").json() == []


def test_checks_api(signed_in):
    client = signed_in
    root = str(Path(__file__).parent / "codebase_examples")
    codebase = next((c for c in client.get("/api/state").json()["codebases"] if c["root"] == root), None) \
        or client.post("/api/codebases", json={"root": root, "name": "Shop"}, headers=WRITE).json()
    wait_for_jobs(client)
    findings = client.get(f"/api/codebases/{codebase['id']}/checks").json()
    assert isinstance(findings, list) and all({"kind", "message", "examples", "confidence"} <= set(f) for f in findings)


def test_tables_as_code_api(signed_in, monkeypatch):
    from tests.conftest import MESSAGE_FOOTERS, make_pdf, message_standard
    client = signed_in
    pdf = make_pdf(message_standard(), header="XYZ-STD-9999", footers=MESSAGE_FOOTERS)
    client.post("/api/documents?filename=XYZ-STD-9999A.pdf", content=pdf, headers=WRITE)
    wait_for_jobs(client)
    doc = next(d for d in client.get("/api/state").json()["documents"] if d["title"].startswith("XYZ-STD-9999A"))
    page = client.get(f"/api/documents/{doc['id']}/pages/2").json()
    table = next(b for b in page["blocks"] if b["kind"] == "table" and b["text"].startswith("TABLE 5.1-1"))
    code = client.get(f"/api/blocks/{table['id']}/as-code?language=typescript").json()
    assert code["constants"] == ["REFERENCE_NUMBER", "STRENGTH"] and "as const" in code["text"]
    assert client.get(f"/api/blocks/{table['id']}/compare-enum?symbol=0").status_code == 404


def test_trace_api(signed_in, tmp_path):
    from tests.conftest import MESSAGE_FOOTERS, make_pdf, message_standard
    client = signed_in
    if not any(d["title"].startswith("XYZ-STD-9999A") for d in client.get("/api/state").json()["documents"]):
        client.post("/api/documents?filename=XYZ-STD-9999A.pdf", content=make_pdf(message_standard(), header="XYZ-STD-9999", footers=MESSAGE_FOOTERS), headers=WRITE)
    (tmp_path / "code").mkdir()
    (tmp_path / "code/Message.java").write_text('public class Message { static final String F = "GRP/ITM 281/001"; }\n')
    codebase = client.post("/api/codebases", json={"root": str(tmp_path / "code"), "name": "Trace"}, headers=WRITE).json()
    wait_for_jobs(client)
    mentions = client.get("/api/catalogue/code?id=GRP/ITM%20281/001").json()
    assert [(m["line"], m["certainty"]) for m in mentions if m["codebase_id"] == codebase["id"]] == [(1, "exact")]
    file = client.get(f"/api/codebases/{codebase['id']}/files").json()[0]
    assert [(i["identifier"], i["line"]) for i in client.get(f"/api/code/files/{file['id']}/identifiers").json()] == [("GRP/ITM 281/001", 1)]


def test_git_and_rename_api(signed_in, tmp_path):
    import shutil
    client = signed_in
    shutil.copytree(Path(__file__).parent / "codebase_examples", tmp_path / "shop")
    codebase = client.post("/api/codebases", json={"root": str(tmp_path / "shop"), "name": "GitRename"}, headers=WRITE).json()
    wait_for_jobs(client)
    info = client.get(f"/api/codebases/{codebase['id']}/git").json()
    assert info["repository"] is False and info["reason"]
    find = next(s for s in client.get(f"/api/codebases/{codebase['id']}/symbols?q=find").json() if s["qualified"].endswith("OrderRepository#find"))
    preview = client.post(f"/api/code/symbols/{find['id']}/rename/preview", json={"name": "lookup"}, headers=WRITE).json()
    assert len(preview["edits"]) == 4 and all(e["selected"] for e in preview["edits"])
    assert client.post(f"/api/code/symbols/{find['id']}/rename/preview", json={"name": "1bad"}, headers=WRITE).status_code == 400
    done = client.post(f"/api/code/symbols/{find['id']}/rename", json={"name": "lookup", "edits": [e["key"] for e in preview["edits"]]}, headers=WRITE).json()
    assert done["edits_applied"] == 4 and done["skipped"] == []
    assert "repository.lookup(" in (tmp_path / "shop/backend/src/main/java/com/shop/service/OrderService.java").read_text()
