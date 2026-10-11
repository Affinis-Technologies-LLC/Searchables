"""
Angular and React, which are to be first-class (ADR-001), on a small app of each (tests/codebase_web).

The passing tests protect what the index reads. Gaps the assistant work must close are added as
strict expected failures (`xfail(strict=True)`), so closing one makes its test fail until the mark
is removed, which keeps this file an honest list. The ADR-010 gaps are now closed.
"""
import sqlite3

import pytest

from src.code.store import CodeStore
from tests.test_code import SAMPLE

WEB = SAMPLE.parent / "codebase_web"


@pytest.fixture(scope="module")
def web():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    store = CodeStore(conn)
    codebase = store.add(str(WEB), "Web")
    store.index(codebase.id)
    return store, codebase


def symbol(store, codebase, qualified):
    found = [s for s in store.search_symbols(codebase.id, qualified.split("#")[-1]) if s.qualified == qualified]
    assert found, f"no symbol {qualified}"
    return found[0]


def ref(store, codebase, path_end, line, name):
    row = store.conn.execute(
        "SELECT r.target_id, r.target FROM code_refs r JOIN code_files f ON f.id = r.file_id "
        "WHERE f.codebase_id = ? AND f.path LIKE ? AND r.line = ? AND r.name = ?", (codebase.id, "%" + path_end, line, name)).fetchone()
    assert row is not None, f"no reference to {name} at {path_end}:{line}"
    return row


# ---- What's read today ------------------------------------------------------------------------

def test_angular_classes_members_and_decorated_fields(web):
    store, codebase = web
    component = symbol(store, codebase, "UserListComponent")
    assert [m.name for m in store.members(component.id)] == ["title", "selected", "users", "constructor", "userService", "ngOnInit", "choose", "remove"]
    assert [s.qualified for s in store.hierarchy(component).supertypes] == [] and store.hierarchy(component).external_supertypes == ["@angular/core#OnInit"]
    assert ref(store, codebase, "user-list.component.ts", 9, "Input")["target"] == "@angular/core#Input"
    assert ref(store, codebase, "user-list.component.ts", 10, "EventEmitter")["target"] == "@angular/core#EventEmitter"
    assert ref(store, codebase, "user-list.component.ts", 24, "ngOnInit")["target_id"] == symbol(store, codebase, "UserListComponent#ngOnInit").id


def test_angular_path_alias_and_http_calls(web):
    store, codebase = web
    imports = store.imports_of(symbol(store, codebase, "UserListComponent").file_id)
    assert [i["target_path"] or i["external"] for i in imports] == ["@angular/core", "angular/src/app/users/user.service.ts"]
    served, unmatched = store.endpoints(codebase.id)
    assert {(e.method, e.path) for e in unmatched} == {("GET", "/api/users"), ("DELETE", "/api/users/{}")}
    assert {d.name for d in store.declared(codebase.id)} >= {"@angular/core", "rxjs", "react"}


def test_react_hooks_components_and_default_exports(web):
    store, codebase = web
    assert ref(store, codebase, "UserList.tsx", 6, "useUsers")["target_id"] == symbol(store, codebase, "useUsers").id
    assert ref(store, codebase, "UserList.tsx", 7, "useState")["target"] == "react#useState"
    assert ref(store, codebase, "App.jsx", 4, "UserList")["target_id"] == symbol(store, codebase, "UserList").id   # <UserList />
    assert ref(store, codebase, "UserCard.tsx", 10, "memo")["target"] == "react#memo"
    usages = store.usages(symbol(store, codebase, "useUsers"))
    assert [(u.path.rsplit("/", 1)[-1], u.line, u.certainty) for u in usages] == [("UserList.tsx", 6, "resolved")]


# ---- Gaps to close (ADR-001, layer 1) ---------------------------------------------------------

def test_calls_through_injected_services_are_linked(web):
    store, codebase = web
    assert ref(store, codebase, "user-list.component.ts", 16, "list")["target_id"] == symbol(store, codebase, "UserService#list").id
    assert ref(store, codebase, "user-list.component.ts", 24, "remove")["target_id"] == symbol(store, codebase, "UserService#remove").id


def test_calls_through_typed_fields_name_the_outside_api(web):
    store, codebase = web
    assert ref(store, codebase, "user.service.ts", 12, "get")["target"] == "@angular/common#HttpClient.get"   # The npm package


def test_class_decorators_are_recorded(web):
    store, codebase = web
    assert ref(store, codebase, "user-list.component.ts", 4, "Component")["target"] == "@angular/core#Component"
    assert ref(store, codebase, "user.service.ts", 7, "Injectable")["target"] == "@angular/core#Injectable"


def test_wrapped_default_exports_resolve(web):
    store, codebase = web
    assert ref(store, codebase, "UserList.tsx", 11, "UserCard")["target_id"] == symbol(store, codebase, "UserCard").id


def test_templates_refer_to_components_and_their_methods(web):
    store, codebase = web
    component = symbol(store, codebase, "UserListComponent")
    assert any(u.path.endswith("app.component.ts") for u in store.usages(component))            # <app-user-list> in the inline template
    assert any(u.path.endswith("user-list.component.html") for u in store.usages(symbol(store, codebase, "UserListComponent#choose")))


def test_chained_calls_carry_the_type_along(web):
    store, codebase = web
    assert ref(store, codebase, "user-list.component.ts", 16, "subscribe")["target"] == "rxjs#Observable.subscribe"
    assert ref(store, codebase, "user-list.component.ts", 20, "emit")["target"] == "@angular/core#EventEmitter.emit"


def test_symbols_know_their_types(web):
    store, codebase = web
    assert symbol(store, codebase, "UserService#list").type == "Observable<User[]>"
    assert symbol(store, codebase, "UserListComponent#users").type == "User[]"
    assert symbol(store, codebase, "UserListComponent#userService").type == "UserService"     # From the constructor parameter


def test_module_metadata_refers_to_components(web):
    store, codebase = web
    users = store.usages(symbol(store, codebase, "AppComponent"))
    assert any(u.path.endswith("app.module.ts") and u.certainty == "resolved" for u in users)
