"""Python SDK for the Finn API (https://api.hirefinn.ai/v1).

    from finn import Finn
    finn = Finn()  # reads FINN_API_KEY
    for call in finn.calls.list_all(status="completed"):
        print(call["call_uuid"])
"""
from . import types
from ._approval import PendingApproval, is_pending_approval
from ._client import AsyncFinn, Finn
from ._core import (
    AUTO_IDEMPOTENCY_ROUTES,
    DEFAULT_BASE_URL,
    DEFAULT_MAX_RETRY_WAIT,
    DEFAULT_FINN_VERSION,
    IDEMPOTENT_WRITE_ROUTES,
    honours_idempotency_key,
    idempotency_key,
)
from ._errors import (
    AuthenticationError,
    BadRequestError,
    ConflictError,
    FinnApprovalTimeoutError,
    FinnConnectionError,
    FinnError,
    FinnFieldError,
    FinnSdkError,
    FinnTimeoutError,
    InternalServerError,
    NotFoundError,
    PayloadTooLargeError,
    PaymentRequiredError,
    PermissionDeniedError,
    RateLimitError,
    code_for_status,
    parse_retry_after,
)
from ._pagination import AsyncPaginator, SyncPaginator
from ._types import ApprovalHold, FinnResponse
from ._version import __version__
from ._webhooks import (
    DEFAULT_WEBHOOK_TOLERANCE,
    WEBHOOK_EVENT_HEADER,
    WEBHOOK_SIGNATURE_HEADER,
    FinnWebhookVerificationError,
    WebhookEvent,
    parse_signature_header,
    sign_webhook_payload,
    verify_webhook,
)

__all__ = [
    "AUTO_IDEMPOTENCY_ROUTES",
    "DEFAULT_BASE_URL",
    "DEFAULT_WEBHOOK_TOLERANCE",
    "IDEMPOTENT_WRITE_ROUTES",
    "DEFAULT_MAX_RETRY_WAIT",
    "DEFAULT_FINN_VERSION",
    "WEBHOOK_EVENT_HEADER",
    "WEBHOOK_SIGNATURE_HEADER",
    "ApprovalHold",
    "AsyncFinn",
    "AsyncPaginator",
    "AuthenticationError",
    "BadRequestError",
    "ConflictError",
    "Finn",
    "FinnApprovalTimeoutError",
    "FinnConnectionError",
    "FinnError",
    "FinnFieldError",
    "FinnResponse",
    "FinnSdkError",
    "FinnTimeoutError",
    "FinnWebhookVerificationError",
    "InternalServerError",
    "NotFoundError",
    "PayloadTooLargeError",
    "PaymentRequiredError",
    "PendingApproval",
    "PermissionDeniedError",
    "RateLimitError",
    "SyncPaginator",
    "WebhookEvent",
    "__version__",
    "code_for_status",
    "honours_idempotency_key",
    "idempotency_key",
    "is_pending_approval",
    "parse_retry_after",
    "parse_signature_header",
    "sign_webhook_payload",
    "types",
    "verify_webhook",
]
