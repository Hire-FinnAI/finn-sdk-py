"""Ports the 44 vitest cases of finn-sdk-ts (test/client.test.ts), same order and names, plus async parity."""
from __future__ import annotations

import asyncio
import email.utils
import re
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from helpers import async_client, body_of, client, json_, text_

from finn import (
    DEFAULT_MAX_RETRY_WAIT,
    honours_idempotency_key,
    AUTO_IDEMPOTENCY_ROUTES,
    BadRequestError,
    ConflictError,
    Finn,
    FinnApprovalTimeoutError,
    FinnConnectionError,
    FinnError,
    FinnSdkError,
    FinnTimeoutError,
    InternalServerError,
    NotFoundError,
    PaymentRequiredError,
    PendingApproval,
    PermissionDeniedError,
    RateLimitError,
    idempotency_key,
    is_pending_approval,
    parse_retry_after,
)

CALL_ID = "b7e3c9a2-4d1f-4e8b-9a6c-2f5d8e1b3c70"
FINN_ID = "8f14e45f-ceea-467a-9f6a-1c0e5b2a77d1"
CALL_BODY = {"finn_id": FINN_ID, "to_number": "4155550142", "country_code": "1"}


def search(req: httpx.Request) -> str:
    q = urlsplit(str(req.url)).query
    return f"?{q}" if q else ""


def qparam(req: httpx.Request, name: str):
    return parse_qs(urlsplit(str(req.url)).query).get(name, [None])[0]


# ---------------------------------------------------------------- construction and headers


class TestConstructionAndHeaders:
    def test_needs_an_api_key(self, monkeypatch):
        monkeypatch.delenv("FINN_API_KEY", raising=False)
        with pytest.raises(FinnSdkError):
            Finn()

    def test_reads_finn_api_key_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("FINN_API_KEY", "finn_live_from_env")
        finn, calls, _ = client([json_(200, {"success": True, "data": {}})], api_key=None)
        finn.wallet.retrieve()
        assert calls[0].headers["authorization"] == "Bearer finn_live_from_env"

    def test_sends_bearer_auth_accept_and_the_default_base_url(self):
        finn, calls, _ = client([json_(200, {"success": True, "data": {"call_uuid": CALL_ID}})])
        finn.calls.retrieve(CALL_ID)
        req = calls[0]
        assert str(req.url) == f"https://api.hirefinn.ai/v1/calls/{CALL_ID}"
        assert req.method == "GET"
        assert req.headers["authorization"] == "Bearer finn_live_test_key"
        assert req.headers["accept"] == "application/json"
        assert "finn-org" not in req.headers
        assert "finn-version" not in req.headers
        assert "idempotency-key" not in req.headers

    def test_sends_finn_org_and_finn_version_from_the_client_overridable_per_request(self):
        finn, calls, _ = client(
            [json_(200, {"success": True, "data": []})],
            api_key="finn_oat_token",
            org="org-a",
            version="2026-11-01",
            base_url="https://example.test/api/v1/",
        )
        finn.finns.list()
        finn.finns.list(org="org-b", version="2026-12-01")
        assert str(calls[0].url) == "https://example.test/api/v1/finns"
        assert calls[0].headers["finn-org"] == "org-a"
        assert calls[0].headers["finn-version"] == "2026-11-01"
        assert calls[1].headers["finn-org"] == "org-b"
        assert calls[1].headers["finn-version"] == "2026-12-01"
        assert calls[1].headers["authorization"] == "Bearer finn_oat_token"

    def test_never_lets_a_per_request_header_replace_authorization(self):
        finn, calls, _ = client([json_(200, {})])
        finn.wallet.retrieve(extra_headers={"Authorization": "Bearer other", "X-Trace": "1"})
        assert calls[0].headers["authorization"] == "Bearer finn_live_test_key"
        assert calls[0].headers["x-trace"] == "1"

    def test_builds_query_strings_and_encodes_path_params(self):
        finn, calls, _ = client([json_(200, {})])
        finn.calls.list(status="completed,voicemail", limit=10, finn_id=None)
        finn.do_not_call.remove("+1 415/555")
        assert str(calls[0].url) == "https://api.hirefinn.ai/v1/calls?status=completed%2Cvoicemail&limit=10"
        assert str(calls[1].url) == "https://api.hirefinn.ai/v1/do_not_call/%2B1%20415%2F555"
        assert calls[1].method == "DELETE"

    def test_sends_json_bodies(self):
        finn, calls, _ = client([json_(201, {"success": True, "data": {}})])
        finn.contacts.add_note("rec_1", {"text": "hello"})
        assert calls[0].headers["content-type"] == "application/json"
        assert body_of(calls[0]) == {"text": "hello"}

    def test_typed_generic_request_works_for_any_path(self):
        finn, calls, _ = client([json_(200, {"success": True, "data": {"call_uuid": CALL_ID}})])
        res = finn.request("get", "/calls/{call_uuid}", path_params={"call_uuid": CALL_ID})
        assert str(calls[0].url) == f"https://api.hirefinn.ai/v1/calls/{CALL_ID}"
        assert res["data"]["call_uuid"] == CALL_ID

    def test_request_with_response_exposes_status_request_id_and_idempotent_replayed(self):
        finn, _, _ = client([json_(200, {"balance": 1}, {"x-request-id": "req_1", "idempotent-replayed": "true"})])
        res = finn.request_with_response("get", "/wallet")
        assert res.status == 200
        assert res.request_id == "req_1"
        assert res.idempotent_replayed is True
        assert res.data == {"balance": 1}


# ---------------------------------------------------------------- idempotency

UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


class TestIdempotency:
    def test_idempotency_key_makes_uuid_v4_strings(self):
        a = idempotency_key()
        assert UUID4.match(a)
        assert idempotency_key() != a

    def test_adds_an_idempotency_key_to_spending_writes_automatically(self):
        finn, calls, _ = client([json_(202, {"success": True, "data": {"call_uuid": CALL_ID}})])
        finn.calls.create(CALL_BODY)
        assert UUID4.match(calls[0].headers["idempotency-key"])

    def test_uses_the_caller_key_when_given_and_none_when_idempotency_key_is_false(self):
        finn, calls, _ = client([json_(202, {"success": True, "data": {}})])
        finn.calls.create(CALL_BODY, idempotency_key="my-key-1")
        finn.calls.create(CALL_BODY, idempotency_key=False)
        assert calls[0].headers["idempotency-key"] == "my-key-1"
        assert "idempotency-key" not in calls[1].headers

    def test_adds_keys_for_chat_send_agent_create_and_case_start(self):
        finn, calls, _ = client([json_(201, {})])
        finn.chat.conversations.send("conv_1", {"text": "hi"})
        finn.agents.create({"name": "Bot"})
        finn.cases.start("agent_1")
        assert len(calls) == 3
        assert all(c.headers.get("idempotency-key") for c in calls)
        assert str(calls[2].url) == "https://api.hirefinn.ai/v1/agents/agent_1/cases"

    def test_does_not_add_keys_to_other_writes_or_when_auto_idempotency_is_off(self):
        finn, calls, _ = client([json_(200, {})], auto_idempotency=False)
        finn.calls.create({"finn_id": FINN_ID, "to_number": "1", "country_code": "1"})
        finn.finns.update(FINN_ID, {})
        assert "idempotency-key" not in calls[0].headers
        assert "idempotency-key" not in calls[1].headers

    def test_keeps_the_same_key_across_retries(self):
        finn, calls, _ = client([json_(503, {"error": "unavailable"}), json_(202, {"success": True, "data": {}})])
        finn.calls.create({"finn_id": FINN_ID, "to_number": "1", "country_code": "1"})
        assert len(calls) == 2
        assert calls[0].headers["idempotency-key"] == calls[1].headers["idempotency-key"]


# ---------------------------------------------------------------- retries


class TestRetries:
    def test_retries_get_on_5xx_with_exponential_backoff_then_succeeds(self):
        finn, calls, sleeps = client(
            [json_(502, {"error": "unavailable"}), json_(504, {"error": "unavailable"}),
             json_(200, {"success": True, "data": []})]
        )
        finn.finns.list()
        assert len(calls) == 3
        assert len(sleeps) == 2
        assert 0.375 <= sleeps[0] <= 0.5
        assert 0.75 <= sleeps[1] <= 1.0

    def test_honours_retry_after_on_429(self):
        finn, _, sleeps = client(
            [json_(429, {"error": "rate_limited", "message": "Slow down"}, {"retry-after": "7"}), json_(200, {})]
        )
        finn.wallet.retrieve()
        assert sleeps == [7]

    def test_throws_instead_of_waiting_out_a_retry_after_longer_than_max_retry_after(self):
        finn, calls, _ = client([json_(429, {"code": "cap_reached", "message": "Daily cap"}, {"retry-after": "3600"})])
        with pytest.raises(FinnError) as ei:
            finn.cases.list()
        assert isinstance(ei.value, RateLimitError)
        assert ei.value.code == "cap_reached"
        assert ei.value.retry_after == 3600
        assert len(calls) == 1

    def test_gives_up_after_max_retries_and_throws_the_last_error(self):
        finn, calls, _ = client([json_(503, {"error": "unavailable", "message": "down"})], max_retries=3)
        with pytest.raises(FinnError) as ei:
            finn.wallet.retrieve()
        assert ei.value.status == 503
        assert isinstance(ei.value, InternalServerError)
        assert len(calls) == 4

    def test_retries_network_errors_on_get(self):
        finn, calls, _ = client([httpx.ConnectError("fetch failed"), json_(200, {})])
        finn.wallet.retrieve()
        assert len(calls) == 2

    def test_wraps_a_final_network_error_in_finn_connection_error(self):
        finn, _, _ = client([httpx.ConnectError("fetch failed")], max_retries=0)
        with pytest.raises(FinnConnectionError) as ei:
            finn.wallet.retrieve()
        assert isinstance(ei.value.__cause__, httpx.ConnectError)

    def test_does_not_retry_a_post_without_an_idempotency_key(self):
        finn, calls, _ = client([json_(503, {"error": "unavailable"}), json_(201, {})])
        with pytest.raises(FinnError):
            finn.finns.create({})
        assert len(calls) == 1

    def test_does_not_retry_a_post_without_a_key_on_network_errors_either(self):
        finn, calls, _ = client([httpx.RemoteProtocolError("socket hang up"), json_(201, {})])
        with pytest.raises(FinnConnectionError):
            finn.contacts.create({"phone": "1"})
        assert len(calls) == 1

    def test_retries_a_post_with_an_explicit_key_on_a_route_that_dedupes_by_it(self):
        finn, calls, _ = client([json_(503, {"error": "unavailable"}), json_(201, {})])
        finn.calls.create(CALL_BODY, idempotency_key="k1")
        assert len(calls) == 2
        assert calls[1].headers["idempotency-key"] == "k1"

    def test_retries_a_keyed_webhook_endpoint_create(self):
        # The API replays the first endpoint (and its secret) for the same key (v1_webhooks_require_idem, on by default).
        finn, calls, _ = client([json_(503, {"error": "unavailable"}), json_(201, {})])
        finn.webhooks.create_endpoint({"url": "https://example.com/h", "events": ["call.completed"]}, idempotency_key="w1")
        assert len(calls) == 2
        assert calls[1].headers["idempotency-key"] == "w1"
        assert honours_idempotency_key("post", "/webhook_endpoints")
        assert not honours_idempotency_key("patch", "/webhook_endpoints/e1")
        assert not honours_idempotency_key("post", "/webhook_endpoints/e1/rotate_secret")

    def test_gives_webhook_endpoint_create_an_automatic_key_reused_on_retry(self):
        finn, calls, _ = client([json_(503, {"error": "unavailable"}), json_(201, {})])
        finn.webhooks.create_endpoint({"url": "https://example.com/h", "events": ["call.completed"]})
        assert len(calls) == 2
        key = calls[0].headers.get("idempotency-key")
        assert key
        assert calls[1].headers["idempotency-key"] == key
        assert "post /webhook_endpoints" in AUTO_IDEMPOTENCY_ROUTES

    def test_does_not_retry_a_keyed_post_on_a_route_that_ignores_the_key(self):
        finn, calls, _ = client([json_(503, {"error": "unavailable"}), json_(201, {})])
        with pytest.raises(FinnError):
            finn.finns.create({}, idempotency_key="k1")
        assert len(calls) == 1
        finn2, calls2, _ = client([httpx.RemoteProtocolError("socket hang up"), json_(201, {})])
        with pytest.raises(FinnConnectionError):
            finn2.finns.create({}, idempotency_key="k2")
        assert len(calls2) == 1

    def test_retries_a_keyed_raw_post_to_a_dedupe_route_given_as_a_filled_in_path(self):
        finn, calls, _ = client([json_(502, {"error": "unavailable"}), json_(201, {})])
        finn.request_with_response("post", "/crm/records/r1/notes", body={}, idempotency_key="k3")
        assert len(calls) == 2

    def test_does_not_retry_500(self):
        finn, calls, _ = client([json_(500, {"error": "internal_error"}), json_(200, {})])
        with pytest.raises(FinnError) as ei:
            finn.wallet.retrieve()
        assert ei.value.status == 500
        assert len(calls) == 1

    def test_knows_which_writes_dedupe_by_idempotency_key(self):
        assert honours_idempotency_key("post", "/calls")
        assert honours_idempotency_key("POST", "/chat/conversations/c1/messages")
        assert honours_idempotency_key("post", "/agents/{id}/cases")
        assert honours_idempotency_key("patch", "/crm/records/r1")
        assert not honours_idempotency_key("post", "/finns")
        assert not honours_idempotency_key("post", "/contacts")
        assert not honours_idempotency_key("post", "/approvals/a1/decide")
        assert not honours_idempotency_key("post", "/calls/extra")

    def test_retries_409_idempotency_in_progress_but_not_other_409s(self):
        a, a_calls, _ = client(
            [json_(409, {"error": {"code": "idempotency_in_progress", "message": "x", "fields": [], "request_id": None,
                                   "doc_url": "u"}}), json_(201, {})]
        )
        a.agents.create({"name": "A"})
        assert len(a_calls) == 2
        b, b_calls, _ = client([json_(409, {"error": "deployment_already_active", "message": "x", "deployment_id": "d1"})])
        with pytest.raises(ConflictError) as ei:
            b.deployments.create_outbound({})
        assert len(b_calls) == 1
        assert ei.value.code == "deployment_already_active"
        assert ei.value.details["deployment_id"] == "d1"

    def test_does_not_retry_4xx(self):
        finn, calls, _ = client([json_(404, {"error": "finn_not_found", "message": "No such Finn"})])
        with pytest.raises(NotFoundError) as ei:
            finn.finns.retrieve(FINN_ID)
        assert (ei.value.status, ei.value.code) == (404, "finn_not_found")
        assert len(calls) == 1

    def test_times_out_an_attempt_with_finn_timeout_error(self):
        finn, calls, _ = client([httpx.ReadTimeout("timed out")], timeout=0.02, max_retries=0)
        with pytest.raises(FinnTimeoutError):
            finn.wallet.retrieve()
        assert calls[0].extensions["timeout"]["read"] == 0.02

    def test_stops_when_the_caller_aborts(self):
        async def run():
            started = asyncio.Event()

            async def hang(_req):
                started.set()
                await asyncio.sleep(3600)

            finn, calls, sleeps = async_client([])
            finn._client = httpx.AsyncClient(transport=httpx.MockTransport(hang))
            task = asyncio.ensure_future(finn.wallet.retrieve())
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert sleeps == []  # not retried

        asyncio.run(run())

    def test_parses_retry_after_as_seconds_or_an_http_date(self):
        assert parse_retry_after("3") == 3
        assert parse_retry_after(email.utils.formatdate(10, usegmt=True), now=4) == 6
        assert parse_retry_after("soon") is None
        assert parse_retry_after(None) is None


# ---------------------------------------------------------------- errors


class TestErrors:
    def test_reads_the_unified_error_body(self):
        finn, _, _ = client([json_(400, {"error": {
            "code": "invalid_request",
            "message": "The request is not valid.",
            "fields": [{"field": "limit", "code": "out_of_range", "message": "must be an integer from 1 to 200"}],
            "request_id": "req_body",
            "doc_url": "https://api.hirefinn.ai/docs/errors#invalid_request",
        }}, {"x-request-id": "req_header"})])
        with pytest.raises(FinnError) as ei:
            finn.agents.list(limit=999)
        e = ei.value
        assert isinstance(e, BadRequestError)
        assert (e.status, e.code, e.message, e.request_id) == (400, "invalid_request", "The request is not valid.", "req_body")
        assert str(e) == "The request is not valid."
        assert e.doc_url == "https://api.hirefinn.ai/docs/errors#invalid_request"
        assert e.fields == [{"field": "limit", "code": "out_of_range", "message": "must be an integer from 1 to 200"}]

    def test_reads_the_legacy_error_message_body_and_its_extras(self):
        finn, _, _ = client([json_(402, {"error": "insufficient_credits", "message": "Top up",
                                         "action_url": "https://app/wallet", "required_credits": 50},
                                   {"x-request-id": "req_9"})])
        with pytest.raises(PaymentRequiredError) as ei:
            finn.phone_numbers.rent({})
        e = ei.value
        assert (e.status, e.code, e.message, e.request_id, e.action_url) == (
            402, "insufficient_credits", "Top up", "req_9", "https://app/wallet")
        assert e.details["required_credits"] == 50

    def test_reads_insufficient_scope_with_required_scope(self):
        finn, _, _ = client([json_(403, {"error": "insufficient_scope", "message": "Needs crm:write",
                                         "required_scope": "crm:write"})])
        with pytest.raises(PermissionDeniedError) as ei:
            finn.contacts.create({"phone": "1"})
        assert ei.value.required_scope == "crm:write"

    def test_reads_the_operator_code_message_details_body(self):
        finn, _, _ = client([json_(409, {"code": "conflict", "message": "Already decided", "details": None})])
        with pytest.raises(FinnError) as ei:
            finn.approvals.approve("appr_1")
        assert (ei.value.status, ei.value.code, ei.value.message) == (409, "conflict", "Already decided")

    def test_falls_back_to_a_code_from_the_status_for_non_json_bodies(self):
        finn, _, _ = client([text_(502, "<html>Bad gateway</html>")], max_retries=0)
        with pytest.raises(FinnError) as ei:
            finn.wallet.retrieve()
        assert (ei.value.status, ei.value.code) == (502, "unavailable")


# ---------------------------------------------------------------- pagination


class TestPagination:
    def test_walks_offset_lists_until_a_short_page(self):
        finn, calls, _ = client([
            json_(200, {"success": True, "data": [{"call_uuid": "1"}, {"call_uuid": "2"}], "total": 5, "limit": 2, "offset": 0}),
            json_(200, {"success": True, "data": [{"call_uuid": "3"}, {"call_uuid": "4"}], "total": 5, "limit": 2, "offset": 2}),
            json_(200, {"success": True, "data": [{"call_uuid": "5"}], "total": 5, "limit": 2, "offset": 4}),
        ])
        ids = [c["call_uuid"] for c in finn.calls.list_all(limit=2, status="completed")]
        assert ids == ["1", "2", "3", "4", "5"]
        assert [search(c) for c in calls] == [
            "?status=completed&limit=2",
            "?status=completed&limit=2&offset=2",
            "?status=completed&limit=2&offset=4",
        ]

    def test_walks_cursor_lists_until_has_more_is_false(self):
        finn, calls, _ = client([
            json_(200, {"data": [{"id": "a"}], "next_cursor": "c1", "has_more": True}),
            json_(200, {"data": [{"id": "b"}], "next_cursor": None, "has_more": False}),
        ])
        items = finn.agents.list_all(limit=1).to_list()
        assert [a["id"] for a in items] == ["a", "b"]
        assert qparam(calls[1], "cursor") == "c1"
        assert len(calls) == 2

    def test_walks_approvals_cursor_approvals_key_cases_before_and_contacts_page(self):
        a, _, _ = client([json_(200, {"approvals": [{"id": "x"}], "next_cursor": "n"}),
                          json_(200, {"approvals": [{"id": "y"}], "next_cursor": None})])
        assert [x["id"] for x in a.approvals.list_all().to_list()] == ["x", "y"]

        c, c_calls, _ = client([json_(200, {"cases": [{"id": "1"}], "next_before": "2026-11-01T00:00:00Z"}),
                                json_(200, {"cases": [{"id": "2"}], "next_before": None})])
        assert len(c.cases.list_all().to_list()) == 2
        assert qparam(c_calls[1], "before") == "2026-11-01T00:00:00Z"

        r, r_calls, _ = client([
            json_(200, {"contacts": [{"id": "r1"}], "page": 1, "pageSize": 1, "totalCount": 2, "totalPages": 2}),
            json_(200, {"contacts": [{"id": "r2"}], "page": 2, "pageSize": 1, "totalCount": 2, "totalPages": 2}),
        ])
        assert len(r.contacts.list_all(page_size=1).to_list()) == 2
        assert qparam(r_calls[1], "page") == "2"
        assert len(r_calls) == 2

    def test_pages_yields_raw_pages_and_to_list_respects_its_limit(self):
        finn, calls, _ = client([json_(200, {"data": [{"id": "a"}, {"id": "b"}], "next_cursor": "c", "has_more": True})])
        first = finn.chat.conversations.list_all().to_list(1)
        assert len(first) == 1
        assert len(calls) == 1
        pages = []
        for p in finn.agents.list_all().pages():
            pages.append(p)
            break
        assert pages[0]["next_cursor"] == "c"

    def test_stops_on_an_empty_page(self):
        finn, calls, _ = client([json_(200, {"data": [], "next_cursor": "loop", "has_more": True})])
        assert finn.agents.list_all().to_list() == []
        assert len(calls) == 1


# ---------------------------------------------------------------- pending approval (202)

PENDING = {
    "status": "pending_approval",
    "approval_id": "hold_1",
    "approve_url": "https://app.hirefinn.ai/approvals/holds/hold_1",
    "expires_at": "2026-11-07T00:00:00.000Z",
    "action": "call.create",
    "summary": {"title": "Place a call"},
}


def hold(status: str):
    return {"id": "hold_1", "object": "approval", "source": "api_hold", "status": status,
            "result": {"status": 202, "body": {"success": True}} if status == "succeeded" else None}


class TestPendingApproval:
    def test_is_pending_approval_narrows_a_held_write(self):
        finn, _, _ = client([json_(202, PENDING)])
        res = finn.calls.create({"finn_id": FINN_ID, "to_number": "1", "country_code": "1"})
        assert is_pending_approval(res)
        assert isinstance(res, PendingApproval)
        assert "hold_1" in (res.approve_url or "")
        assert res.approval_id == "hold_1"
        assert res.action == "call.create"
        assert res.raw == PENDING
        assert not is_pending_approval({"success": True, "data": {"status": "initiated"}})
        assert not is_pending_approval(None)

    def test_wait_for_approval_polls_until_a_final_status(self):
        finn, calls, _ = client([json_(200, hold("pending")), json_(200, hold("running")), json_(200, hold("succeeded"))])
        waits, seen = [], []
        out = finn.wait_for_approval("hold_1", interval=1, sleep=waits.append, on_poll=lambda a: seen.append(a["status"]))
        assert out["status"] == "succeeded"
        assert seen == ["pending", "running", "succeeded"]
        assert waits == [1, 1]
        assert all(str(c.url) == "https://api.hirefinn.ai/v1/approvals/hold_1" for c in calls)

    def test_wait_for_approval_treats_an_operator_approval_leaving_open_as_final_and_unwraps_data(self):
        finn, _, _ = client([json_(200, {"data": {"id": "a1", "status": "open"}}),
                             json_(200, {"data": {"id": "a1", "status": "decided"}})])
        out = finn.wait_for_approval("a1", sleep=lambda s: None)
        assert out["status"] == "decided"

    def test_wait_for_approval_times_out_with_finn_approval_timeout_error(self):
        finn, _, _ = client([json_(200, {"id": "h", "status": "pending"})])
        with pytest.raises(FinnApprovalTimeoutError) as ei:
            finn.wait_for_approval("h", interval=0.01, timeout=0, sleep=lambda s: None)
        assert ei.value.last_status == "pending"


class TestRetryBudget:
    """max_retry_wait (default 20 s) caps the total wait between retries of one request."""

    def test_waits_out_retry_after_on_503_for_a_get_while_it_fits_the_budget(self):
        finn, calls, sleeps = client(
            [json_(503, {"error": "unavailable"}, {"retry-after": "8"}),
             json_(503, {"error": "unavailable"}, {"retry-after": "8"}),
             json_(200, {"success": True, "data": []})]
        )
        finn.finns.list()
        assert len(calls) == 3
        assert sleeps == [8, 8]

    def test_stops_before_the_total_wait_would_pass_20s_and_raises_the_last_error(self):
        finn, calls, sleeps = client(
            [json_(503, {"error": "unavailable"}, {"retry-after": "15"}),
             json_(503, {"error": "unavailable"}, {"retry-after": "15"})],
            max_retries=5,
        )
        with pytest.raises(FinnError) as ei:
            finn.finns.list()
        assert ei.value.status == 503
        assert len(calls) == 2
        assert sleeps == [15]

    def test_can_be_raised_per_client(self):
        finn, calls, _ = client(
            [json_(504, {}, {"retry-after": "30"}), json_(200, {"success": True, "data": []})], max_retry_wait=60
        )
        finn.finns.list()
        assert len(calls) == 2

    def test_async_respects_the_budget_too(self):
        finn, calls, sleeps = async_client(
            [json_(502, {}, {"retry-after": "12"}), json_(502, {}, {"retry-after": "12"})], max_retries=5
        )
        with pytest.raises(FinnError):
            asyncio.run(finn.finns.list())
        assert len(calls) == 2
        assert sleeps == [12]

    def test_retries_a_keyed_dialer_note_but_never_an_unkeyed_one(self):
        finn, calls, _ = client([json_(502, {}), json_(201, {"success": True, "data": {}})])
        finn.dialer.add_call_note("c1", {"note": "hi"}, idempotency_key="k1")
        assert len(calls) == 2
        assert calls[0].headers["idempotency-key"] == calls[1].headers["idempotency-key"] == "k1"

        finn, calls, _ = client([json_(502, {}), json_(201, {})])
        with pytest.raises(FinnError):
            finn.dialer.add_call_note("c1", {"note": "hi"})
        assert len(calls) == 1

    def test_new_rolling_out_writes_are_deduped_only_where_the_api_dedupes_them(self):
        assert honours_idempotency_key("PATCH", "/chat/agents/a1")
        assert honours_idempotency_key("POST", "/chat/agents/a1/test_turn")
        assert honours_idempotency_key("POST", "/dialer/follow-ups/c1/done")
        assert not honours_idempotency_key("POST", "/webhook_endpoints/w1/rotate_secret")
        assert not honours_idempotency_key("POST", "/agents/a1/archive")
        assert DEFAULT_MAX_RETRY_WAIT == 20.0
