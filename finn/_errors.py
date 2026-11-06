"""Errors raised by the SDK.

The API answers errors in one of three shapes, and FinnError reads all of them:

- unified (newer endpoints: Agents, Chat, and errors raised by shared middleware on them):
  ``{"error": {"code", "message", "fields", "request_id", "doc_url"}}``
- legacy (older /v1 endpoints): ``{"error": "<code>", "message": "...", ...extra}``
- Operator pass-through (Cases, Approvals): ``{"code": "<code>", "message": "...", "details": ...}``

Branch on ``code``, never on ``message``. Each HTTP status also has its own subclass (NotFoundError,
RateLimitError, ...), so ``except finn.NotFoundError`` works too.
"""
from __future__ import annotations

import email.utils
import re
import time
from typing import Any, Dict, List, Mapping, Optional, Type, cast

from ._compat import TypedDict


class FinnFieldError(TypedDict):
    """One per-field problem. ``field`` is a dotted path into the body or query, e.g. ``variables.first_name``."""

    field: str
    code: str
    message: str


_CODE_FOR_STATUS = {
    400: "invalid_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    413: "payload_too_large",
    422: "invalid_request",
    429: "rate_limited",
    500: "internal_error",
    502: "unavailable",
    503: "unavailable",
    504: "unavailable",
}


def code_for_status(status: int) -> str:
    """The code an error gets when the body does not name one (mirrors the backend's codeForStatus)."""
    return _CODE_FOR_STATUS.get(status, "internal_error" if status >= 500 else "invalid_request")


class FinnSdkError(Exception):
    """Base class for every error the SDK raises."""


class FinnError(FinnSdkError):
    """The API answered with a 4xx or 5xx status."""

    def __init__(
        self,
        *,
        status: int,
        code: str,
        message: str,
        request_id: Optional[str] = None,
        fields: Optional[List[FinnFieldError]] = None,
        doc_url: Optional[str] = None,
        action_url: Optional[str] = None,
        required_scope: Optional[str] = None,
        retry_after: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
        body: Any = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        #: HTTP status.
        self.status = status
        #: Stable error code, e.g. ``invalid_request``, ``insufficient_scope``, ``finn_not_found``.
        self.code = code
        #: Matches the ``X-Request-Id`` response header; quote it to support.
        self.request_id = request_id
        #: Per-field problems (unified shape only; ``[]`` otherwise).
        self.fields: List[FinnFieldError] = list(fields or [])
        #: Link to the error's documentation, when the API sent one.
        self.doc_url = doc_url
        #: Dashboard page that fixes the problem (``compliance_required``, ``insufficient_credits``, ...).
        self.action_url = action_url
        #: The scope the key lacks, on ``403 insufficient_scope``.
        self.required_scope = required_scope
        #: Seconds the API asked us to wait (Retry-After), when sent.
        self.retry_after = retry_after
        #: Extra fields from legacy and Operator bodies (``details``, ``deployment_id``, ``required_credits``, ...).
        self.details: Dict[str, Any] = dict(details or {})
        #: The parsed response body (or raw text when it was not JSON).
        self.body = body
        #: Response headers.
        self.headers: Mapping[str, str] = headers if headers is not None else {}

    def __repr__(self) -> str:
        return f"{type(self).__name__}(status={self.status}, code={self.code!r}, message={self.message!r})"

    @classmethod
    def from_response(
        cls, status: int, headers: Mapping[str, str], body: Any, reason: str = ""
    ) -> "FinnError":
        """Builds the right FinnError subclass from a failed response and its already-read body."""
        header_request_id = _header(headers, "x-request-id")
        base: Dict[str, Any] = {
            "status": status,
            "headers": headers,
            "body": body,
            "retry_after": parse_retry_after(_header(headers, "retry-after")),
        }
        obj = body if isinstance(body, dict) else None
        err_cls = error_class_for_status(status)

        if obj is not None and isinstance(obj.get("error"), dict):
            e = obj["error"]
            rest = {k: v for k, v in obj.items() if k != "error"}
            fields = e.get("fields")
            return err_cls(
                **base,
                code=_str(e.get("code")) or code_for_status(status),
                message=_str(e.get("message")) or _default_message(status, reason),
                request_id=_str(e.get("request_id")) or header_request_id,
                fields=[cast(FinnFieldError, f) for f in fields if isinstance(f, dict) and isinstance(f.get("field"), str)]
                if isinstance(fields, list)
                else [],
                doc_url=_str(e.get("doc_url")),
                action_url=_str(e.get("action_url")) or _str(obj.get("action_url")),
                required_scope=_str(e.get("required_scope")) or _str(obj.get("required_scope")),
                details=rest,
            )
        if obj is not None and isinstance(obj.get("error"), str):
            skip = {"error", "message", "action_url", "required_scope", "request_id"}
            return err_cls(
                **base,
                code=obj["error"] or code_for_status(status),
                message=_str(obj.get("message")) or _default_message(status, reason),
                request_id=_str(obj.get("request_id")) or header_request_id,
                action_url=_str(obj.get("action_url")),
                required_scope=_str(obj.get("required_scope")),
                details={k: v for k, v in obj.items() if k not in skip},
            )
        if obj is not None and isinstance(obj.get("code"), str):
            skip = {"code", "message", "request_id"}
            return err_cls(
                **base,
                code=obj["code"],
                message=_str(obj.get("message")) or _default_message(status, reason),
                request_id=_str(obj.get("request_id")) or header_request_id,
                details={k: v for k, v in obj.items() if k not in skip},
            )
        text = body.strip() if isinstance(body, str) else ""
        return err_cls(
            **base,
            code=code_for_status(status),
            message=text if text and len(body) < 500 else _default_message(status, reason),
            request_id=header_request_id,
        )


class BadRequestError(FinnError):
    """400 / 422: the request is not valid (see ``fields``)."""


class AuthenticationError(FinnError):
    """401: missing, invalid or revoked API key or token."""


class PaymentRequiredError(FinnError):
    """402: not enough credits (``insufficient_credits``; see ``action_url``)."""


class PermissionDeniedError(FinnError):
    """403: the key lacks a scope (``required_scope``) or the action is not allowed."""


class NotFoundError(FinnError):
    """404."""


class ConflictError(FinnError):
    """409: e.g. ``deployment_already_active``, ``idempotency_key_reused``."""


class PayloadTooLargeError(FinnError):
    """413."""


class RateLimitError(FinnError):
    """429: slow down; ``retry_after`` says for how long."""


class InternalServerError(FinnError):
    """5xx."""


_CLASS_FOR_STATUS: Dict[int, Type[FinnError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    402: PaymentRequiredError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    413: PayloadTooLargeError,
    422: BadRequestError,
    429: RateLimitError,
}


def error_class_for_status(status: int) -> Type[FinnError]:
    if status >= 500:
        return InternalServerError
    return _CLASS_FOR_STATUS.get(status, FinnError)


class FinnConnectionError(FinnSdkError):
    """The request never got an HTTP answer (DNS, connection reset, TLS, ...). The cause is in ``__cause__``."""


class FinnTimeoutError(FinnConnectionError):
    """An attempt took longer than ``timeout``."""


class FinnApprovalTimeoutError(FinnSdkError):
    """wait_for_approval gave up before the approval reached a final status."""

    def __init__(self, approval_id: str, last_status: Optional[str]) -> None:
        super().__init__(
            f"Approval {approval_id} was still {last_status or 'unknown'} when wait_for_approval timed out."
        )
        self.approval_id = approval_id
        #: The last status seen.
        self.last_status = last_status


def parse_retry_after(value: Optional[str], now: Optional[float] = None) -> Optional[float]:
    """Retry-After as seconds: accepts delta-seconds or an HTTP date. ``now`` is a Unix time in seconds."""
    if value is None or value.strip() == "":
        return None
    v = value.strip()
    if re.fullmatch(r"\d+(\.\d+)?", v):
        return float(v) if "." in v else int(v)
    try:
        parsed = email.utils.parsedate_to_datetime(v)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed is None:
        return None
    current = time.time() if now is None else now
    return max(0.0, parsed.timestamp() - current)


def _header(headers: Mapping[str, str], name: str) -> Optional[str]:
    getter = getattr(headers, "get", None)
    if getter is None:
        return None
    value = getter(name)
    if value is None:
        for k, v in headers.items():
            if k.lower() == name:
                return v
    return value


def _str(v: Any) -> Optional[str]:
    return v if isinstance(v, str) and v != "" else None


def _default_message(status: int, reason: str) -> str:
    return f"Finn API request failed with status {status}{(' ' + reason) if reason else ''}."
