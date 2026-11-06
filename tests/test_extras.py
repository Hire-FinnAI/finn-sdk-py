"""Behaviour the TS suite does not cover: typed exception classes, multipart, the generator, the client lifecycle."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from helpers import client, json_

from finn import (
    AuthenticationError,
    BadRequestError,
    Finn,
    FinnError,
    FinnSdkError,
    InternalServerError,
    PayloadTooLargeError,
    code_for_status,
)

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "status,cls",
    [(400, BadRequestError), (401, AuthenticationError), (413, PayloadTooLargeError), (422, BadRequestError),
     (418, FinnError), (504, InternalServerError)],
)
def test_status_picks_the_exception_class(status, cls):
    finn, _, _ = client([json_(status, {})], max_retries=0)
    with pytest.raises(cls) as ei:
        finn.wallet.retrieve()
    assert type(ei.value) is cls
    assert ei.value.code == code_for_status(status)


def test_multipart_upload_sends_files_and_form_fields_without_json():
    finn, calls, _ = client([json_(201, {"success": True, "data": {}})])
    finn.finns.add_knowledge_base_document("f1", {"name": "Policy"}, files={"file": ("p.txt", b"hello", "text/plain")})
    req = calls[0]
    assert req.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert b'name="name"' in req.content and b"Policy" in req.content and b"hello" in req.content


def test_if_match_header_on_save_draft():
    finn, calls, _ = client([json_(200, {})])
    finn.agents.save_draft("a1", {}, if_match='"v3"')
    assert calls[0].method == "PUT"
    assert calls[0].headers["if-match"] == '"v3"'


def test_missing_path_param_raises_before_sending():
    finn, calls, _ = client([json_(200, {})])
    with pytest.raises(FinnSdkError):
        finn.calls.retrieve("")
    assert calls == []


def test_sync_context_manager_closes_its_own_client_but_not_a_passed_one():
    with Finn(api_key="finn_live_x") as finn:
        inner = finn._client
    assert inner.is_closed
    finn2, _, _ = client([json_(200, {})])
    passed = finn2._client
    finn2.close()
    assert not passed.is_closed


def _load_generator():
    spec = importlib.util.spec_from_file_location("finn_generate", ROOT / "scripts" / "generate.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_generated_code_matches_the_vendored_spec():
    gen_mod = _load_generator()
    spec = json.loads((ROOT / "spec" / "openapi.json").read_text("utf-8"))
    gen = gen_mod.TypeGen(spec)
    gen.build_components()
    ops = gen_mod.load_ops(gen)
    gen_mod.SCHEMA_NAMES.update(name for name, _ in gen.classes)
    gen_mod.SCHEMA_NAMES.update(gen.aliases)
    out = ROOT / "finn" / "_generated"
    assert (out / "schemas.py").read_text("utf-8") == gen.render(), "run python scripts/generate.py"
    assert (out / "resources.py").read_text("utf-8") == gen_mod.render_resources(gen, ops)
    assert (out / "request.py").read_text("utf-8") == gen_mod.render_request(ops)


def test_every_spec_operation_has_a_resource_method():
    gen_mod = _load_generator()
    spec = json.loads((ROOT / "spec" / "openapi.json").read_text("utf-8"))
    ops = gen_mod.load_ops(gen_mod.TypeGen(spec))
    mapped = set()

    def walk(res):
        for c in res.get("children", []):
            walk(c)
        mapped.update(m["op"] for m in res["methods"])

    for r in gen_mod.RESOURCES:
        walk(r)
    assert set(ops) - mapped == set()
    assert mapped - set(ops) == set()
