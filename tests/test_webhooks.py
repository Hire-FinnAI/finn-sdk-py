"""verify_webhook: signature and timestamp checks, matching the backend's signing scheme."""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from finn import FinnWebhookVerificationError, parse_signature_header, sign_webhook_payload, verify_webhook

SECRET = "whsec_test_0123456789abcdef"
BODY = json.dumps({"event": "call.completed", "created_at": "2026-11-06T10:00:00.000Z", "data": {"call_uuid": "c1"}})
T = 1_793_000_000


def backend_sign(secret: str, t: int, body: str) -> str:
    """What services/webhookDeliveryService.js sends: t=<unix>,v1=<hex HMAC-SHA256(secret, "<t>.<body>")>."""
    mac = hmac.new(secret.encode(), f"{t}.{body}".encode(), hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def test_accepts_a_backend_signed_delivery_and_returns_the_event():
    event = verify_webhook(BODY, backend_sign(SECRET, T, BODY), SECRET, now=T + 10)
    assert event["event"] == "call.completed"
    assert event["data"]["call_uuid"] == "c1"


def test_reads_the_header_from_a_headers_mapping_and_takes_bytes():
    sig = backend_sign(SECRET, T, BODY)
    assert verify_webhook(BODY.encode(), secret=SECRET, headers={"x-finn-signature": sig}, now=T)
    assert verify_webhook(BODY, secret=SECRET, headers={"X-Finn-Signature": sig}, now=T)


def test_sign_webhook_payload_matches_the_backend():
    assert f"t={T},v1={sign_webhook_payload(SECRET, T, BODY)}" == backend_sign(SECRET, T, BODY)


@pytest.mark.parametrize(
    "payload,header,secret,match",
    [
        (BODY, backend_sign(SECRET, T, BODY), "whsec_other", "does not match"),
        (BODY.replace("c1", "c2"), backend_sign(SECRET, T, BODY), SECRET, "does not match"),
        (BODY, "v1=abc", SECRET, "Malformed"),
        (BODY, f"t={T},v1=zzé", SECRET, "does not match"),
        (BODY, None, SECRET, "Missing X-Finn-Signature"),
        (BODY, backend_sign(SECRET, T, BODY), "", "Missing webhook signing secret"),
    ],
)
def test_rejects_bad_deliveries(payload, header, secret, match):
    with pytest.raises(FinnWebhookVerificationError, match=match):
        verify_webhook(payload, header, secret, now=T)


def test_rejects_timestamps_outside_the_tolerance_either_side():
    sig = backend_sign(SECRET, T, BODY)
    assert verify_webhook(BODY, sig, SECRET, now=T + 300)
    for now in (T + 301, T - 301):
        with pytest.raises(FinnWebhookVerificationError, match="tolerance"):
            verify_webhook(BODY, sig, SECRET, now=now)
    assert verify_webhook(BODY, sig, SECRET, now=T + 1000, tolerance=1200)


def test_accepts_any_of_several_secrets_while_rotating():
    assert verify_webhook(BODY, backend_sign(SECRET, T, BODY), ["whsec_new", SECRET], now=T)


def test_accepts_a_two_signature_header_during_the_24h_rotation_overlap_with_either_secret():
    # Backend (P3-04 rotate_secret): t=<unix>,v1=<hmac current secret>,v1=<hmac previous secret>.
    old, new = SECRET, "whsec_rotated_fedcba9876543210"

    def mac(s: str) -> str:
        return hmac.new(s.encode(), f"{T}.{BODY}".encode(), hashlib.sha256).hexdigest()

    header = f"t={T},v1={mac(new)},v1={mac(old)}"
    assert verify_webhook(BODY, header, old, now=T)
    assert verify_webhook(BODY, header, new, now=T)
    assert verify_webhook(BODY, header, [new, old], now=T)
    with pytest.raises(FinnWebhookVerificationError):
        verify_webhook(BODY, header, "whsec_other", now=T)
    with pytest.raises(FinnWebhookVerificationError):
        verify_webhook(BODY + " ", header, [new, old], now=T)
    with pytest.raises(FinnWebhookVerificationError, match="tolerance"):
        verify_webhook(BODY, header, new, now=T + 301)


def test_refuses_parsed_json_as_the_payload():
    with pytest.raises(FinnWebhookVerificationError, match="raw request body"):
        verify_webhook(json.loads(BODY), backend_sign(SECRET, T, BODY), SECRET, now=T)  # type: ignore[arg-type]


def test_parses_the_header():
    assert parse_signature_header("t=12, v1=AB ,v1=cd,v0=x") == (12, ["ab", "cd"])
