# Finn Python SDK

Python client for the [Finn API](https://api.hirefinn.ai/docs) (`https://api.hirefinn.ai/v1`): calls, Finns,
voices, phone numbers, audiences, campaigns, wallet, do-not-call, CRM records, Operator cases, approvals, agents and
chat.

- Sync (`Finn`) and async (`AsyncFinn`) clients on [httpx](https://www.python-httpx.org/), the only dependency.
- Typed: every request body, query parameter and response in the spec is a `TypedDict` (`finn.types`), generated
  from the API's OpenAPI spec.
- Retries with backoff on network errors, 408, 429 and 5xx, honouring `Retry-After`.
- Automatic `Idempotency-Key` on spending and outward writes, kept the same across retries.
- One iterator over every list style (cursor, offset, page, before).
- Typed exceptions for the API's error shapes; held writes come back as `PendingApproval`.

Python 3.9 or newer.

## Install

```sh
pip install hirefinn          # not published yet; until then:
pip install git+https://github.com/Hire-FinnAI/finn-sdk-py.git
```

The distribution is called `hirefinn` (the name `finn` on PyPI belongs to another project); you import `finn`.

## Quickstart

```python
from finn import Finn, is_pending_approval

finn = Finn()  # reads FINN_API_KEY; or Finn(api_key="finn_live_...")

# Place a call
call = finn.calls.create({"finn_id": "8f14e45f-...", "to_number": "4155550142", "country_code": "1"})
if is_pending_approval(call):
    print("Waiting for a person to approve:", call.approve_url)
    outcome = finn.wait_for_approval(call.approval_id)
else:
    print(call["data"]["call_uuid"])

# Read one
c = finn.calls.retrieve(call_uuid)
print(c["data"]["status"])

# Every completed call, page by page under the hood
for summary in finn.calls.list_all(status="completed", limit=100):
    print(summary["call_uuid"])

# CRM
rec = finn.contacts.create({"kind": "contact", "name": "Ada Lovelace", "phone": "+14155550142"})
finn.contacts.add_note(rec["data"]["id"], {"text": "Asked for a callback on Monday."})
```

Async:

```python
import asyncio
from finn import AsyncFinn

async def main() -> None:
    async with AsyncFinn() as finn:
        agents = await finn.agents.list(limit=20)
        async for conv in finn.chat.conversations.list_all():
            print(conv["id"])

asyncio.run(main())
```

Use the client as a context manager (`with Finn() as finn:`) or call `finn.close()` to release connections.

## Client options

| Option | Default | |
| --- | --- | --- |
| `api_key` | env `FINN_API_KEY` | `finn_live_...` org key, `finn_test_...` test key, or OAuth `finn_oat_...` token |
| `base_url` | `https://api.hirefinn.ai/v1` | |
| `org` | none | `Finn-Org` header, for tokens that can use more than one org |
| `version` | none | Pins the API version (`Finn-Version` header), e.g. `"2026-11-01"` |
| `max_retries` | `2` | Retries after the first attempt |
| `timeout` | `60` | Seconds per attempt |
| `auto_idempotency` | `True` | Generate `Idempotency-Key` on spending/outward writes |
| `max_retry_after` | `60` | Longest `Retry-After` (seconds) to wait out; longer raises |
| `default_headers` | none | Sent on every request |
| `http_client` | new `httpx.Client` | Bring your own (proxies, custom transport); the SDK does not close it |

Every method also takes the per-request keyword options `idempotency_key`, `org`, `version`, `max_retries`,
`timeout` and `extra_headers`, which override the client's setting for that call only. `extra_headers` can never
replace `Authorization`.

## Resources

| Attribute | Methods |
| --- | --- |
| `calls` | `create`, `list`, `list_all`, `retrieve` |
| `finns` | `list`, `list_all`, `create`, `retrieve`, `update`, `delete`, `list_knowledge_base`, `add_knowledge_base_document`, `post_call_analysis` |
| `voices` | `list`, `list_all`, `retrieve` |
| `phone_numbers` | `list`, `list_all`, `search_available`, `rent`, `retrieve`, `release` |
| `audiences` | `list`, `list_all`, `create`, `retrieve`, `archive`, `list_contacts`, `list_all_contacts`, `add_contacts`, `remove_contact` |
| `deployments` | `list`, `list_all`, `create_outbound`, `create_inbound`, `retrieve`, `stop`, `stop_inbound`, `analytics` |
| `wallet` | `retrieve`, `list_transactions`, `list_all_transactions` |
| `do_not_call` | `list`, `list_all`, `add`, `remove` |
| `contacts` | `list`, `list_all`, `create`, `retrieve`, `update`, `timeline`, `timeline_all`, `add_note`, `list_kinds`, `list_fields` |
| `cases` | `list`, `list_all`, `retrieve`, `list_events`, `start` |
| `approvals` | `list`, `list_all`, `retrieve`, `decide`, `approve`, `reject`, `wait` |
| `agents` | `list`, `list_all`, `create`, `draft`, `retrieve`, `save_draft`, `validate`, `test`, `publish`, `drive_test` |
| `chat` | `list_channels`; `chat.conversations`: `list`, `list_all`, `start`, `retrieve`, `list_messages`, `list_all_messages`, `send`; `chat.contacts`: `list`, `list_all`, `retrieve`, `update` |

Path parameters are positional, the request body is the next positional argument (a dict), and query parameters
are keyword arguments (`from` is spelled `from_`). Knowledge-base uploads take `files=`:

```python
with open("policy.pdf", "rb") as f:
    finn.finns.add_knowledge_base_document(finn_id, {"name": "Refund policy"}, files={"file": f})
```

Anything else, including endpoints newer than this SDK, goes through `request` (typed by method and path) or
`request_with_response` (untyped, returns status, headers and request id):

```python
call = finn.request("get", "/calls/{call_uuid}", path_params={"call_uuid": call_uuid})
res = finn.request_with_response("get", "/wallet")
print(res.status, res.request_id, res.idempotent_replayed, res.data)
```

## Retries

Failed attempts are retried up to `max_retries` times on network errors, 408, 429, 5xx and
`409 idempotency_in_progress`, waiting `Retry-After` when the API sends it and otherwise backing off exponentially
(0.5 s, 1 s, 2 s ... up to 8 s, with jitter). A `Retry-After` longer than `max_retry_after` raises at once.
Only requests that are safe to repeat are retried: `GET`, `PUT`, `DELETE`, and writes that carry an
`Idempotency-Key`.

## Idempotency keys

The SDK adds a random `Idempotency-Key` to `calls.create`, `phone_numbers.rent`, `deployments.create_outbound`,
`deployments.create_inbound`, `chat.conversations.start`, `chat.conversations.send`, `agents.create` and
`cases.start`, and keeps it across retries. Pass your own to make a retry from your side safe too, or `False` to
send none:

```python
finn.calls.create(body, idempotency_key=f"order-{order_id}")
finn.calls.create(body, idempotency_key=False)
```

## Errors

Every API error raises `finn.FinnError` (or a subclass by status: `BadRequestError`, `AuthenticationError`,
`PaymentRequiredError`, `PermissionDeniedError`, `NotFoundError`, `ConflictError`, `PayloadTooLargeError`,
`RateLimitError`, `InternalServerError`). Branch on `code`, never on the message.

```python
from finn import FinnError, NotFoundError

try:
    finn.finns.retrieve(finn_id)
except NotFoundError:
    ...
except FinnError as e:
    print(e.status, e.code, e.message, e.request_id)
    print(e.fields)          # per-field problems on invalid_request
    print(e.required_scope)  # on insufficient_scope
    print(e.action_url)      # dashboard page that fixes it (insufficient_credits, ...)
    print(e.retry_after, e.doc_url, e.details)
```

No HTTP answer at all raises `FinnConnectionError` (`FinnTimeoutError` when an attempt timed out).
`FinnSdkError` is the base of everything the SDK raises.

## Approvals

Outward and spending writes from OAuth and MCP callers may be held for a person to approve. They answer HTTP 202,
which the SDK returns as a `PendingApproval` (`approval_id`, `approve_url`, `expires_at`, `action`, `summary`).
`finn.wait_for_approval(id)` polls until the approval is decided and returns it; for a held request, `status` ends
as `succeeded`, `failed`, `declined` or `expired`, and `result` holds the held request's own answer.

## Pagination

`list_all(...)` methods return a paginator: iterate it for items, `.pages()` for raw pages, `.to_list(limit)` to
collect. Async paginators work with `async for` and `await .to_list()`.

## Regenerating from the spec

The spec is vendored in `spec/openapi.json`. To refresh it from a local checkout of the backend (prod branch):

```sh
BACKEND=../hirefinn-web-app-backend ./scripts/pull-spec.sh
# or from a file or URL:
python scripts/generate.py path/or/url/to/openapi.json
```

`scripts/generate.py` (standard library only) writes `finn/_generated/`: TypedDicts for every schema, the
resource classes (grouped by the `RESOURCES` table in the script) and typed overloads for `request()`. It fails if
the table names an operation the spec lacks, and lists spec operations the table does not cover.

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

The tests use `httpx.MockTransport` and never touch the network; one of them type-checks a sample with mypy.
