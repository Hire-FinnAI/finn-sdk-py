"""Not a test module: test_types.py runs mypy over it. Each `# type: ignore[code]` marks an error mypy must report
(--warn-unused-ignores fails the run if it does not)."""
from __future__ import annotations

from typing import Any, Dict, Union

from typing_extensions import assert_type

from finn import AsyncFinn, Finn, PendingApproval, SyncPaginator, WebhookEvent, verify_webhook
from finn.types import (
    AgentSummary,
    CallSummary,
    CaseStarted,
    CreateCallResponse,
    ListCallsResponse,
    RetrieveCallResponse,
)


def sync_checks(finn: Finn) -> None:
    listed = finn.calls.list(limit=10)
    assert_type(listed, ListCallsResponse)
    assert_type(listed["data"][0], CallSummary)

    created = finn.calls.create({"finn_id": "f", "to_number": "1", "country_code": "1"})
    assert_type(created, Union[CreateCallResponse, PendingApproval])
    if isinstance(created, PendingApproval):
        assert_type(created.approval_id, str)

    assert_type(finn.agents.list_all(), SyncPaginator[AgentSummary])
    assert_type(finn.chat.conversations.list_all(), SyncPaginator[Dict[str, Any]])

    # Chat start/send and case start can be held for approval too.
    sent = finn.chat.conversations.send("c1", {"content": "hi"})
    assert_type(sent, Union[Dict[str, Any], PendingApproval])
    assert_type(finn.chat.conversations.start({}), Union[Dict[str, Any], PendingApproval])
    assert_type(finn.cases.start("a1"), Union[CaseStarted, PendingApproval])

    assert_type(verify_webhook("{}", "t=1,v1=00", "whsec_x"), WebhookEvent)

    got = finn.request("get", "/calls/{call_uuid}", path_params={"call_uuid": "x"})
    assert_type(got, RetrieveCallResponse)

    finn.calls.create()  # type: ignore[call-arg]
    finn.calls.create({"finn_id": "f"})  # type: ignore[typeddict-item]
    finn.calls.list(limit="ten")  # type: ignore[arg-type]
    finn.request("get", "/calls/{call_uuid}")  # type: ignore[call-overload]
    finn.request("get", "/nope")  # type: ignore[call-overload]


async def async_checks(finn: AsyncFinn) -> None:
    got = await finn.calls.retrieve("x")
    assert_type(got, RetrieveCallResponse)
    async for agent in finn.agents.list_all():
        assert_type(agent, AgentSummary)
