"""AsyncFinn parity: the same core paths as the sync client."""
from __future__ import annotations

import asyncio

import pytest
from helpers import async_client, json_

from finn import FinnConnectionError, NotFoundError, PendingApproval
import httpx


def run(coro):
    return asyncio.run(coro)


def test_async_headers_query_and_body():
    async def go():
        finn, calls, _ = async_client([json_(202, {"success": True, "data": {}})], org="org-a", version="2026-11-01")
        await finn.calls.create({"finn_id": "f", "to_number": "1", "country_code": "1"})
        await finn.calls.list(status="completed", limit=5)
        await finn.close()
        return calls

    calls = run(go())
    assert calls[0].headers["authorization"] == "Bearer finn_live_test_key"
    assert calls[0].headers["finn-org"] == "org-a"
    assert calls[0].headers["finn-version"] == "2026-11-01"
    assert calls[0].headers["idempotency-key"]
    assert str(calls[1].url) == "https://api.hirefinn.ai/v1/calls?status=completed&limit=5"


def test_async_retries_honour_retry_after_and_keep_the_key():
    async def go():
        finn, calls, sleeps = async_client(
            [json_(429, {"error": "rate_limited"}, {"retry-after": "2"}), json_(201, {"id": "a"})]
        )
        out = await finn.agents.create({"name": "A"})
        return out, calls, sleeps

    out, calls, sleeps = run(go())
    assert out == {"id": "a"}
    assert sleeps == [2]
    assert calls[0].headers["idempotency-key"] == calls[1].headers["idempotency-key"]


def test_async_errors_and_connection_errors():
    async def go():
        a, _, _ = async_client([json_(404, {"error": "finn_not_found", "message": "No such Finn"})])
        with pytest.raises(NotFoundError):
            await a.finns.retrieve("x")
        b, calls, _ = async_client([httpx.ConnectError("down")], max_retries=1)
        with pytest.raises(FinnConnectionError):
            await b.wallet.retrieve()
        return calls

    assert len(run(go())) == 2


def test_async_pagination_and_pending_approval():
    async def go():
        finn, _, _ = async_client([
            json_(200, {"data": [{"id": "a"}], "next_cursor": "c1", "has_more": True}),
            json_(200, {"data": [{"id": "b"}], "next_cursor": None, "has_more": False}),
        ])
        ids = [a["id"] async for a in finn.agents.list_all()]
        held, _, _ = async_client([json_(202, {"status": "pending_approval", "approval_id": "h1", "approve_url": "u"})])
        res = await held.phone_numbers.rent({"phone_number": "+14155550142"})  # type: ignore[typeddict-unknown-key]
        return ids, res

    ids, res = run(go())
    assert ids == ["a", "b"]
    assert isinstance(res, PendingApproval) and res.approval_id == "h1"


def test_async_wait_for_approval():
    async def go():
        finn, _, _ = async_client([json_(200, {"id": "h", "status": "pending"}), json_(200, {"id": "h", "status": "declined"})])
        waits = []

        async def sleep(s):
            waits.append(s)

        out = await finn.wait_for_approval("h", interval=2, sleep=sleep)
        return out, waits

    out, waits = run(go())
    assert out["status"] == "declined"
    assert waits == [2]


def test_async_context_manager_closes_its_own_client():
    async def go():
        from finn import AsyncFinn

        async with AsyncFinn(api_key="finn_live_x") as finn:
            inner = finn._client
        return inner.is_closed

    assert run(go()) is True
