"""
Examples as you type, and completion from the index (ADR-012): the context of an unsaved buffer at
the cursor, the candidate filters, the ranking features, completion, feedback, and the evaluation tool.
"""
import json
import sqlite3
from pathlib import Path

import pytest

from src import config
from src.code.context import context_at
from src.code.complete import complete_at
from src.code.examples import examples_for, score
from src.code.store import CodeStore

SAMPLE = Path(__file__).parent / "codebase_examples"
ORDER_SERVICE = "backend/src/main/java/com/shop/service/OrderService.java"
CUSTOMER_SERVICE = "backend/src/main/java/com/shop/service/CustomerService.java"
ORDERS_TS = "frontend/src/api/orders.ts"


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    conn = sqlite3.connect(tmp_path_factory.mktemp("lib") / "library.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    store = CodeStore(conn)
    codebase = store.add(str(SAMPLE), "Shop")
    store.index(codebase.id)
    return store


@pytest.fixture(scope="module")
def code(store):
    return store.list_codebases()[0]


def file_named(store, code, ending):
    return next(f for f in store.files(code.id) if f.path.endswith(ending))


def typing(store, code, ending, before: str, typed: str, after: str = ""):
    """A buffer where `typed` has just been written at the point `before` ends; the cursor is after `typed`."""
    file = file_named(store, code, ending)
    text = store.text(file.id)
    assert before in text, before
    position = text.index(before) + len(before)
    buffer = text[:position] + typed + after + text[position:]
    at = position + len(typed)
    line = buffer.count("\n", 0, at) + 1
    col = at - (buffer.rfind("\n", 0, at) + 1) + 1
    return file, buffer, line, col


# ---- The context: what's being written -----------------------------------------------------------

def test_java_context_resolves_the_receiver_and_partial_member(store, code):
    file, buffer, line, col = typing(store, code, ORDER_SERVICE, "    public List<Order> open() {\n", "        repository.fi")
    context = context_at(store, file.id, buffer, line, col)
    assert context.enclosing.qualified == "com.shop.service.OrderService#open"
    assert context.expression.kind == "call" and context.expression.partial == "fi"
    assert context.expression.receiver == "repository" and context.receiver_type.qualified == "com.shop.repo.OrderRepository"
    assert context.receiver_type.certainty == "resolved"
    assert "repository.all" in context.neighbours.calls or "all" in context.neighbours.calls


def test_java_context_inside_the_arguments_of_a_call(store, code):
    file, buffer, line, col = typing(store, code, ORDER_SERVICE, "    public List<Order> open() {\n", "        repository.save(order, ")
    context = context_at(store, file.id, buffer, line, col)
    assert context.expression.kind == "call" and context.expression.name == "save" and context.expression.args_so_far == 2
    assert context.receiver_type.qualified == "com.shop.repo.OrderRepository"


def test_java_context_follows_a_local_variable(store, code):
    file, buffer, line, col = typing(store, code, ORDER_SERVICE, "    public List<Order> open() {\n",
                                     "        Order found = repository.find(1).orElse(null);\n        found.setSt")
    context = context_at(store, file.id, buffer, line, col)
    assert context.receiver_type.qualified == "com.shop.model.Order" and context.expression.partial == "setSt"


def test_java_context_for_new_and_for_nothing_resolved(store, code):
    file, buffer, line, col = typing(store, code, ORDER_SERVICE, "    public List<Order> open() {\n", "        new Ord")
    context = context_at(store, file.id, buffer, line, col)
    assert context.expression.kind == "new" and context.expression.partial == "Ord"
    file, buffer, line, col = typing(store, code, ORDER_SERVICE, "    public List<Order> open() {\n", "        mystery.ping(")
    context = context_at(store, file.id, buffer, line, col)
    assert context.receiver_type is None and context.expression.name == "ping" and context.expression.receiver == "mystery"


def test_typescript_context(store, code):
    file, buffer, line, col = typing(store, code, ORDERS_TS, "export function createOrder(order: Order): Promise<Order> {\n", "  http.po")
    context = context_at(store, file.id, buffer, line, col)
    assert context.enclosing.qualified == "createOrder" and context.expression.partial == "po"
    assert context.receiver_type.qualified == "Http" and context.receiver_type.path.endswith("client.ts")
    file, buffer, line, col = typing(store, code, "frontend/src/hooks/useOrders.ts", "  return orders;\n", "  fetchOr")
    context = context_at(store, file.id, buffer, line, col)
    assert context.expression.kind == "call" and context.expression.receiver == "" and context.expression.partial == "fetchOr"


def test_a_broken_buffer_still_gives_a_context(store, code):
    file, buffer, line, col = typing(store, code, ORDER_SERVICE, "    public List<Order> open() {\n", "        if (repository.fi")
    context = context_at(store, file.id, buffer, line, col)
    assert context.enclosing.qualified == "com.shop.service.OrderService#open"
    assert context.receiver_type.qualified == "com.shop.repo.OrderRepository" and context.expression.partial == "fi"


# ---- Candidates and ranking ------------------------------------------------------------------------

def test_same_member_on_the_same_type_comes_first(store, code):
    file, buffer, line, col = typing(store, code, ORDER_SERVICE, "    public List<Order> open() {\n", "        repository.find(")
    result = examples_for(store, context_at(store, file.id, buffer, line, col))
    assert result.filter == "same member on the same type"
    where = [(e.path.rsplit("/", 1)[-1], e.enclosing.split("#")[-1]) for e in result.examples]
    assert set(where) >= {("OrderService.java", "load"), ("OrderService.java", "cancel"), ("OrderServiceTest.java", "savesAnOrder")}
    assert all(e.features["T"] == 1.0 and e.features["M"] == 1.0 for e in result.examples)
    assert all(e.enclosing != "com.shop.service.OrderService#open" for e in result.examples)   # Never the method being written
    assert len({e.enclosing for e in result.examples}) == len(result.examples)                 # One per method
    assert result.examples[0].reason.startswith("Same `OrderRepository.find`")


def test_siblings_follow_when_the_type_has_few_examples(store, code):
    file, buffer, line, col = typing(store, code, CUSTOMER_SERVICE, "    public Customer lookup(long id) {\n", "        repository.save(")
    result = examples_for(store, context_at(store, file.id, buffer, line, col))
    own = [e for e in result.examples if e.features["T"] == 1.0]
    siblings = [e for e in result.examples if e.features["T"] == 0.5]
    assert [e.enclosing.split("#")[-1] for e in own] == ["register"]
    assert {e.enclosing.split("#")[-1] for e in siblings} >= {"place", "cancel", "savesAnOrder"}
    assert all(e.features["M"] in (0.7, 0.35) for e in siblings)   # Same name on a sibling; the overload counts half
    assert result.examples[0].enclosing.endswith("#register") and own[0].score > siblings[0].score


def test_same_name_anywhere_is_flagged_by_name(store, code):
    file, buffer, line, col = typing(store, code, ORDER_SERVICE, "    public List<Order> open() {\n", "        mystery.save(")
    result = examples_for(store, context_at(store, file.id, buffer, line, col))
    assert result.filter == "same name on any type" and result.by_name
    assert {e.target.rsplit("#", 1)[0].rsplit(".", 1)[-1] for e in result.examples} == {"OrderRepository", "CustomerRepository"}
    assert all(e.features["T"] == 0.3 for e in result.examples)


def test_nothing_resolves_gives_code_from_methods_like_this_one(store, code):
    file, buffer, line, col = typing(store, code, ORDER_SERVICE, "    public void place(Order order) {\n", "        something(")
    result = examples_for(store, context_at(store, file.id, buffer, line, col))
    assert result.filter == "methods like this one"
    assert result.examples and result.examples[0].enclosing in ("com.shop.service.OrderService#cancel", "com.shop.service.CustomerService#register")


def test_context_and_structure_features_prefer_the_closer_method(store, code):
    # Writing in cancel(): load() shares its receiver and find; cancel-like structure (if, assignment) is in cancel itself, excluded
    file, buffer, line, col = typing(store, code, CUSTOMER_SERVICE, "    public Customer lookup(long id) {\n", "        repository.find(")
    result = examples_for(store, context_at(store, file.id, buffer, line, col))
    by_method = {e.enclosing.split("#")[-1]: e for e in result.examples}
    assert by_method["load"].features["C"] > 0 and by_method["load"].features["P"] > 0
    assert 0 <= by_method["load"].features["Q"] <= 1 and by_method["savesAnOrder"].features["Q"] >= by_method["cancel"].features["Q"]


def test_the_score_is_the_weighted_sum_and_the_weights_are_configuration():
    features = {"T": 1.0, "M": 0.5, "C": 0.0, "P": 1.0, "Q": 0.5}
    assert score(features) == pytest.approx(sum(config.EXAMPLE_WEIGHTS[k] * v for k, v in features.items()))
    assert sum(config.EXAMPLE_WEIGHTS.values()) == pytest.approx(1.0)


def test_examples_carry_their_text_and_place(store, code):
    file, buffer, line, col = typing(store, code, ORDER_SERVICE, "    public List<Order> open() {\n", "        audit.rec")
    result = examples_for(store, context_at(store, file.id, buffer, line, col))
    first = result.examples[0]
    assert first.file_id and first.line and first.statement.strip().startswith("audit.record(")
    assert first.start <= first.line <= first.end and len(first.lines) <= 7 and any("audit.record" in l for l in first.lines)


def test_typescript_examples_and_outside_apis(store, code):
    file, buffer, line, col = typing(store, code, ORDERS_TS, "export function createOrder(order: Order): Promise<Order> {\n", "  http.post(")
    result = examples_for(store, context_at(store, file.id, buffer, line, col))
    assert {e.enclosing for e in result.examples} == {"registerCustomer"}   # createOrder is being written
    file, buffer, line, col = typing(store, code, "frontend/src/api/client.ts", "export const http = new Http();\n",
                                     "export function ping(url: string) {\n  return fetch(")
    result = examples_for(store, context_at(store, file.id, buffer, line, col))
    assert result.filter == "same outside API" and {e.enclosing for e in result.examples} == {"Http#get", "Http#post"}


# ---- Completion ------------------------------------------------------------------------------------

def test_completion_after_a_receiver_lists_members_with_example_counts(store, code):
    file, buffer, line, col = typing(store, code, ORDER_SERVICE, "    public List<Order> open() {\n", "        repository.")
    items = complete_at(store, context_at(store, file.id, buffer, line, col))
    by_name = {(i.name, i.params): i for i in items}
    assert ("find", 1) in by_name and by_name[("find", 1)].examples == 3 and by_name[("find", 1)].type == "Optional<Order>"
    assert ("count", 0) in by_name                                            # Inherited from Repository
    assert all(i.kind in ("method", "field") for i in items)
    file, buffer, line, col = typing(store, code, ORDER_SERVICE, "    public List<Order> open() {\n", "        repository.sa")
    assert {i.name for i in complete_at(store, context_at(store, file.id, buffer, line, col))} == {"save"}


def test_completion_without_a_receiver_offers_scope_then_importable_symbols(store, code):
    file, buffer, line, col = typing(store, code, ORDER_SERVICE, "    public void cancel(long id) {\n        Order order = repository.find(id).orElse(null);\n", "        o")
    items = complete_at(store, context_at(store, file.id, buffer, line, col))
    names = [i.name for i in items]
    assert names[0] == "order" and items[0].kind == "variable" and items[0].type == "Order"
    assert "open" in names and "OrderRepository" in names
    importable = next(i for i in items if i.name == "OrderController")
    assert importable.insert_import == "com.shop.web.OrderController"
    file, buffer, line, col = typing(store, code, "frontend/src/hooks/useOrders.ts", "  return orders;\n", "  fetchCu")
    items = complete_at(store, context_at(store, file.id, buffer, line, col))
    assert [(i.name, i.insert_import) for i in items] == [("fetchCustomer", "../api/customers")]


# ---- Feedback ---------------------------------------------------------------------------------------

def test_feedback_is_recorded_locally(store, code):
    file, buffer, line, col = typing(store, code, ORDER_SERVICE, "    public List<Order> open() {\n", "        repository.find(")
    context = context_at(store, file.id, buffer, line, col)
    result = examples_for(store, context)
    store.record_feedback(context.digest, result.examples[0].ref_id, "insert")
    store.record_feedback(context.digest, result.examples[1].ref_id, "dismiss")
    rows = store.feedback()
    assert [(r["action"], r["ref_id"]) for r in rows[-2:]] == [("insert", result.examples[0].ref_id), ("dismiss", result.examples[1].ref_id)]
    assert rows[-1]["digest"] == context.digest and rows[-1]["recorded_at"]


# ---- The evaluation tool -----------------------------------------------------------------------------

def test_evaluate_examples_beats_both_baselines_on_the_judged_set(tmp_path):
    from src.evaluate_examples import evaluate
    report = evaluate(Path(__file__).parent / "examples_set.json", tmp_path / "eval.db")
    for language in ("java", "typescript"):
        ours, text, unranked = report[language]["ranked"], report[language]["text search"], report[language]["unranked"]
        assert ours["precision@3"] > text["precision@3"] and ours["precision@3"] > unranked["precision@3"], (language, report[language])
        assert ours["mrr"] >= unranked["mrr"]
    assert report["java"]["contexts"] >= 8 and report["typescript"]["contexts"] >= 5
