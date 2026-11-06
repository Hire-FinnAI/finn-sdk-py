"""Hand-written types the spec does not describe."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, Mapping, Optional, TypeVar

from ._compat import Literal, TypedDict

T = TypeVar("T")

HoldStatus = Literal["pending", "running", "succeeded", "failed", "declined", "expired"]


class ApprovalHoldResult(TypedDict):
    status: int
    body: Any


# A held API request as GET /approvals/{id} returns it to the caller that made it. Functional syntax because of
# the `class` key.
ApprovalHold = TypedDict(
    "ApprovalHold",
    {
        "id": str,
        "object": Literal["approval"],
        "source": Literal["api_hold"],
        "status": HoldStatus,
        "action": str,
        "class": str,
        "summary": Any,
        "approve_url": Optional[str],
        "expires_at": Optional[str],
        "created_at": Optional[str],
        "decided_at": Optional[str],
        "finished_at": Optional[str],
        "outcome_unknown": bool,
        "result": Optional[ApprovalHoldResult],
    },
    total=False,
)


@dataclass
class FinnResponse(Generic[T]):
    """A response together with its HTTP status and headers."""

    data: T
    status: int
    headers: Mapping[str, str] = field(repr=False)
    #: X-Request-Id.
    request_id: Optional[str] = None
    #: True when the API replayed a saved answer for the same Idempotency-Key.
    idempotent_replayed: bool = False
