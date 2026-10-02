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
