"""HTTP 202 ``pending_approval`` answers, and waiting for an approval to be decided."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, Optional, Union

from ._errors import FinnApprovalTimeoutError

if TYPE_CHECKING:
    from ._generated.schemas import Approval
    from ._types import ApprovalHold

#: Statuses that are still waiting: holds (``pending``, ``running``) and Operator approvals (``open``).
WAITING_STATUSES = frozenset({"pending", "running", "open", "pending_approval"})


@dataclass(frozen=True)
class PendingApproval:
    """A write the API held for a person to approve (HTTP 202) instead of doing it.

    Outward and spending actions from OAuth and MCP callers can answer this. Show ``approve_url`` to a person,
    then ``client.wait_for_approval(approval_id)`` for the outcome.
    """

    approval_id: str
    #: The page in Finn where a person approves it.
    approve_url: Optional[str]
    expires_at: Optional[str] = None
    action: Optional[str] = None
    summary: Any = None
    status: str = "pending_approval"
    #: The full response body.
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_body(cls, body: Dict[str, Any]) -> "PendingApproval":
        return cls(
            approval_id=body["approval_id"],
            approve_url=body.get("approve_url"),
            expires_at=body.get("expires_at"),
            action=body.get("action"),
            summary=body.get("summary"),
            raw=dict(body),
        )


def looks_pending(body: Any) -> bool:
    return isinstance(body, dict) and body.get("status") == "pending_approval" and isinstance(body.get("approval_id"), str)


def is_pending_approval(value: Any) -> bool:
    """True when a write was held for a person to approve (a PendingApproval, or its raw body)."""
    return isinstance(value, PendingApproval) or looks_pending(value)


def unwrap_approval(body: Any) -> Any:
    """GET /approvals/{id} answers the approval itself, or wraps it in ``data`` / ``approval``."""
    if isinstance(body, dict):
        for key in ("data", "approval"):
            if isinstance(body.get(key), dict):
                return body[key]
    return body


def _status(approval: Any) -> Optional[str]:
    s = approval.get("status") if isinstance(approval, dict) else None
    return s if isinstance(s, str) else None


ApprovalResult = Union["Approval", "ApprovalHold"]


class ApprovalWait:
    """Adds wait() to the sync Approvals resource."""

    if TYPE_CHECKING:
        retrieve: Callable[..., ApprovalResult]

    def wait(
        self,
        id: str,
        *,
        interval: float = 3.0,
        timeout: float = 15 * 60.0,
        on_poll: Optional[Callable[[ApprovalResult], None]] = None,
        sleep: Optional[Callable[[float], None]] = None,
    ) -> ApprovalResult:
        """Polls ``GET /approvals/{id}`` until the approval leaves pending / running / open, and returns it.

        For a held API request, ``status`` ends as ``succeeded``, ``failed``, ``declined`` or ``expired``, and
        ``result`` holds the held request's own answer. Raises FinnApprovalTimeoutError after ``timeout`` seconds.
        """
        do_sleep = sleep or time.sleep
        deadline = time.monotonic() + timeout
        while True:
            approval = self.retrieve(id)
            if on_poll:
                on_poll(approval)
            last = _status(approval)
            if last is not None and last not in WAITING_STATUSES:
                return approval
            if time.monotonic() + interval > deadline:
                raise FinnApprovalTimeoutError(id, last)
            do_sleep(interval)


class AsyncApprovalWait:
    """Adds wait() to the async Approvals resource."""

    if TYPE_CHECKING:
        retrieve: Callable[..., Awaitable[ApprovalResult]]

    async def wait(
        self,
        id: str,
        *,
        interval: float = 3.0,
        timeout: float = 15 * 60.0,
        on_poll: Optional[Callable[[ApprovalResult], None]] = None,
        sleep: Optional[Callable[[float], Awaitable[None]]] = None,
    ) -> ApprovalResult:
        """Async wait(); see ApprovalWait.wait."""
        do_sleep = sleep or asyncio.sleep
        deadline = time.monotonic() + timeout
        while True:
            approval = await self.retrieve(id)
            if on_poll:
                on_poll(approval)
            last = _status(approval)
            if last is not None and last not in WAITING_STATUSES:
                return approval
            if time.monotonic() + interval > deadline:
                raise FinnApprovalTimeoutError(id, last)
            await do_sleep(interval)
