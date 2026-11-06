"""Webhook signature checks.

Finn signs every delivery with ``X-Finn-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256(secret, "<t>.<raw body>")>``
and names the event in ``X-Finn-Event``. :func:`verify_webhook` checks the signature in constant time and refuses
deliveries whose timestamp is too far from now, so a captured request cannot be replayed later.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from ._compat import TypedDict
from ._errors import FinnSdkError

#: Header that carries the signature.
WEBHOOK_SIGNATURE_HEADER = "X-Finn-Signature"
#: Header that carries the event name.
WEBHOOK_EVENT_HEADER = "X-Finn-Event"
#: Default largest gap, in seconds, between the signed timestamp and now.
DEFAULT_WEBHOOK_TOLERANCE = 300


class WebhookEvent(TypedDict):
    """The body of every webhook delivery."""

    #: e.g. ``call.completed``, ``contact.created``, ``case.completed``.
    event: str
    created_at: str
    data: Dict[str, Any]


class FinnWebhookVerificationError(FinnSdkError):
    """The delivery's signature is missing, malformed, wrong or too old. Answer the request with a 400."""


def parse_signature_header(header: str) -> Tuple[Optional[int], List[str]]:
    """Splits ``t=...,v1=...`` into its timestamp (None if missing) and v1 signatures."""
    timestamp: Optional[int] = None
    signatures: List[str] = []
    for part in header.split(","):
        k, sep, v = part.partition("=")
        if not sep:
            continue
        k, v = k.strip(), v.strip()
        if k == "t" and re.fullmatch(r"[0-9]+", v):
            timestamp = int(v)
        elif k == "v1" and v:
            signatures.append(v.lower())
    return timestamp, signatures


def sign_webhook_payload(secret: str, timestamp: Union[int, str], payload: Union[str, bytes]) -> str:
    """Hex HMAC-SHA256 of ``<timestamp>.<payload>``, the way Finn signs deliveries."""
    body = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    return hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode("utf-8") + body, hashlib.sha256).hexdigest()


def _read_header(headers: Optional[Mapping[str, Any]]) -> Optional[str]:
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    # Case-insensitive mappings (httpx, requests, Starlette, Werkzeug) answer either spelling.
    if callable(getter):
        for name in (WEBHOOK_SIGNATURE_HEADER, WEBHOOK_SIGNATURE_HEADER.lower()):
            value = getter(name)
            if value:
                return str(value[0] if isinstance(value, (list, tuple)) else value)
    want = WEBHOOK_SIGNATURE_HEADER.lower()
    for k, v in headers.items():
        if str(k).lower() == want and v:
            return str(v[0] if isinstance(v, (list, tuple)) else v)
    return None


def verify_webhook(
    payload: Union[str, bytes],
    header: Optional[str] = None,
    secret: Union[str, Sequence[str]] = "",
    *,
    headers: Optional[Mapping[str, Any]] = None,
    tolerance: float = DEFAULT_WEBHOOK_TOLERANCE,
    now: Optional[float] = None,
) -> WebhookEvent:
    """Checks a webhook delivery and returns its parsed body.

    Args:
        payload: The raw request body, exactly as received (``request.get_data()``, ``await request.body()``).
            Not re-serialised JSON: that changes the bytes that were signed.
        header: The ``X-Finn-Signature`` value. Or pass ``headers=`` to read it from the request's headers.
        secret: The endpoint's signing secret (``whsec_...``). Pass a list while you rotate secrets.
        tolerance: Largest gap between the signed timestamp and now, in seconds. Default 300.
        now: Current unix time (for tests).

    Raises:
        FinnWebhookVerificationError: the signature is missing, malformed or wrong, or the timestamp is too old
            (or too far in the future).

    Example (Flask)::

        event = verify_webhook(request.get_data(), headers=request.headers, secret=os.environ["FINN_WEBHOOK_SECRET"])
    """
    if not isinstance(payload, (str, bytes, bytearray)):
        raise FinnWebhookVerificationError(
            "payload must be the raw request body (str or bytes), not parsed JSON: re-serialising changes the bytes "
            "that were signed."
        )
    secrets = [secret] if isinstance(secret, str) else list(secret)
    secrets = [s for s in secrets if s]
    if not secrets:
        raise FinnWebhookVerificationError("Missing webhook signing secret.")

    value = header if header is not None else _read_header(headers)
    if not value:
        raise FinnWebhookVerificationError(f"Missing {WEBHOOK_SIGNATURE_HEADER} header.")
    timestamp, signatures = parse_signature_header(value)
    if timestamp is None or not signatures:
        raise FinnWebhookVerificationError(f"Malformed {WEBHOOK_SIGNATURE_HEADER} header: expected t=<unix>,v1=<hex>.")

    current = time.time() if now is None else now
    if abs(current - timestamp) > tolerance:
        raise FinnWebhookVerificationError("Webhook timestamp is outside the tolerance window.")

    body = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    ok = False
    for s in secrets:
        expected = sign_webhook_payload(s, timestamp, body).encode("ascii")
        # Check every pair, so the time taken does not reveal which one matched.
        for sig in signatures:
            if hmac.compare_digest(expected, sig.encode("utf-8", "replace")):
                ok = True
    if not ok:
        raise FinnWebhookVerificationError("Webhook signature does not match.")

    try:
        event: WebhookEvent = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise FinnWebhookVerificationError("Webhook body is not valid JSON.") from None
    return event
