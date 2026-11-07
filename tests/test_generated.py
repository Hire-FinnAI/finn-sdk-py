"""Every operation in the spec is a resource method (G4): each one sends the right method and path, sync and async."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple
from urllib.parse import urlsplit

import pytest
from helpers import async_client, body_of, client, json_

from finn import PendingApproval

ROOT = Path(__file__).resolve().parent.parent


def _load_generator() -> Any:
    spec = importlib.util.spec_from_file_location("finn_generate_g4", ROOT / "scripts" / "generate.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


GEN = _load_generator()
SPEC = json.loads((ROOT / "spec" / "openapi.json").read_text("utf-8"))
OPS = GEN.load_ops(GEN.TypeGen(SPEC))


def _methods() -> Iterator[Tuple[Tuple[str, ...], Dict[str, Any]]]:
    def walk(res: Dict[str, Any], trail: Tuple[str, ...]) -> Iterator[Tuple[Tuple[str, ...], Dict[str, Any]]]:
        here = trail + (res["attr"],)
        for child in res.get("children", []):
            yield from walk(child, here)
        for m in res["methods"]:
            if "pager" not in m:
                yield here + (m["name"],), m

    for r in GEN.build_resources(SPEC):
        yield from walk(r, ())


METHODS = list(_methods())


def _args(op: Any, rename: Dict[str, str]) -> Tuple[List[Any], Dict[str, Any], str]:
    """Positional args, keyword args and the expected path for a call to `op`."""
    args: List[Any] = []
    path = op.path
    for i, p in enumerate(op.path_params):
        value = f"p{i}"
        args.append(value)
        path = path.replace("{" + p["name"] + "}", value)
    if op.body_type and op.body_required:
        args.append({})
    kwargs = {GEN.snake(w): "q" for w, _, req in op.query if req}
    return args, kwargs, path


def _resolve(finn: Any, trail: Tuple[str, ...]) -> Any:
    obj = finn
    for attr in trail:
        obj = getattr(obj, attr)
    return obj


def test_the_sdk_has_a_method_for_every_operation_in_the_spec():
    covered = {m["op"] for _, m in METHODS}
    assert len(OPS) == 154
    assert covered == set(OPS)


@pytest.mark.parametrize("trail,entry", METHODS, ids=[".".join(t) for t, _ in METHODS])
def test_each_method_sends_its_operation(trail, entry):
    op = OPS[entry["op"]]
    args, kwargs, path = _args(op, entry.get("rename", {}))
    finn, calls, _ = client([json_(200, {"ok": True})])
    _resolve(finn, trail)(*args, **kwargs)
    assert calls[0].method == op.method.upper()
    assert urlsplit(str(calls[0].url)).path == "/v1" + path

    afinn, acalls, _ = async_client([json_(200, {"ok": True})])
    asyncio.run(_resolve(afinn, trail)(*args, **kwargs))
    assert acalls[0].method == op.method.upper()
    assert urlsplit(str(acalls[0].url)).path == "/v1" + path


def test_crm_record_writes_send_the_body_and_honour_idempotency_keys():
    finn, calls, _ = client([json_(201, {"id": "r1"})])
    out = finn.crm.add_note("r1", {"body": "Called back"}, idempotency_key="k-1")
    assert out == {"id": "r1"}
    assert body_of(calls[0]) == {"body": "Called back"}
    assert calls[0].headers["idempotency-key"] == "k-1"


def test_held_crm_writes_answer_a_pending_approval():
    held = {"status": "pending_approval", "approval_id": "h1", "approve_url": "https://app.hirefinn.ai/a/h1"}
    finn, calls, _ = client([json_(202, held)])
    out = finn.crm.move_record_stage("r1", {"stage": "won"})
    assert isinstance(out, PendingApproval)
    assert out.approval_id == "h1"
    assert urlsplit(str(calls[0].url)).path == "/v1/crm/records/r1/stage_moves"


def test_cursor_pagination_on_new_lists():
    finn, calls, _ = client([
        json_(200, {"data": [{"id": "w1"}], "next_cursor": "c2", "has_more": True}),
        json_(200, {"data": [{"id": "w2"}], "next_cursor": None, "has_more": False}),
    ])
    assert [e["id"] for e in finn.webhooks.list_all_endpoints(limit=1)] == ["w1", "w2"]
    assert "cursor=c2" in str(calls[1].url)


def test_finn_org_comes_from_the_org_option_not_a_method_argument():
    finn, calls, _ = client([json_(200, {"data": []})], org="org-a")
    finn.finns.get_flow("f1", org="org-b")
    assert calls[0].headers["finn-org"] == "org-b"
    for _, entry in METHODS:
        assert "finn_org" not in str(OPS[entry["op"]].headers)


def test_sales_is_marked_experimental():
    finn, _, _ = client([json_(200, {})])
    assert finn.sales.experimental is True
    assert "Experimental" in (type(finn.sales).__doc__ or "")
    assert "Experimental" in (finn.sales.run_play.__doc__ or "")
    assert not getattr(finn.crm, "experimental", False)


def test_generated_names_mirror_the_typescript_sdk():
    # Same names as finn-sdk-ts (scripts/generate.mjs), in snake_case.
    from finn._generated import OPERATIONS

    assert OPERATIONS["getFinnFlow"] == ("get", "/finns/{finn_id}/flow", "finns.get_flow", False)
    assert OPERATIONS["searchCrmRecords"][2] == "crm.search_records"
    assert OPERATIONS["listWebhookEndpoints"][2] == "webhooks.list_endpoints"
    assert OPERATIONS["listEventTypes"][2] == "webhooks.list_event_types"
    assert OPERATIONS["getOrganization"][2] == "organization.get"
    assert OPERATIONS["runSalesPlay"] == ("post", "/sales/plays/{slug}/run", "sales.run_play", True)
    assert OPERATIONS["createCall"][2] == "calls.create"  # hand-written names are kept
    assert len(OPERATIONS) == 154
    assert {k for k, v in OPERATIONS.items() if v[3]} == {
        "listSalesPlays", "listSalesPlayRuns", "listSalesProspects", "runSalesPlay", "listSalesDrafts",
        "updateSalesDraft", "skipSalesDraft", "listSalesThreads", "getSalesThread",
    }


def test_strip_noun_removes_whole_words_only():
    assert GEN.strip_noun("getFinnFlow", ["Finn"]) == "getFlow"
    assert GEN.strip_noun("askCrm", ["Crm"]) == "ask"
    assert GEN.strip_noun("duplicateFinn", ["Finn"]) == "duplicate"
    assert GEN.strip_noun("getFinnsX", ["Finn"]) == "getFinnsX"


def test_readme_coverage_is_current():
    readme = (ROOT / "README.md").read_text("utf-8")
    assert "The SDK covers **154 of 154** operations" in readme
    assert "| `finn.sales` (experimental) |" in readme


def test_method_names_are_snake_case():
    for trail, _ in METHODS:
        assert all(re.fullmatch(r"[a-z][a-z0-9_]*", part) for part in trail), trail
