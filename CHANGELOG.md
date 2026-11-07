# Changelog

## Unreleased

Ships as 0.3.0 if it lands before the 0.3.0 PyPI upload (PyPI has 0.2.0 only; the TypeScript SDK's 0.3.0 is
already on npm, so there these changes need the next version).

### Added: rolling out, flag-gated

These operations come from open Finn API pull requests (not on the live API yet). Until Finn turns them on for an
organization they answer an error, and `python scripts/check_drift.py` against the live spec lists them as extra.

- `finn.webhooks.test_endpoint`, `redeliver_delivery`, `rotate_endpoint_secret` (`POST /webhook_endpoints/{id}/test`,
  `.../deliveries/{delivery_id}/redeliver`, `.../rotate_secret`).
- `finn.agents.archive` (`POST /agents/{id}/archive`).
- `finn.organization.get_usage` (`GET /usage`).
- `finn.dialer.mark_follow_up_done`, `set_call_disposition`, `add_call_note`; `finn.chat.get_agent`,
  `update_agent`, `test_agent` (`/dialer/...`, `/chat/agents/{agent_id}`).

The SDK covers 165 of 165 operations of the merged spec (154 live + 11 rolling out).

### Changed

- Spec refreshed to the live API spec (docs, `V1Error` context entries, `ApiKeyInfo.expiring_soon`).
- Retries: the waits of one request (backoff and `Retry-After`) now add up to at most `max_retry_wait`, default
  20 s; a retry that would go past it throws the last error instead.
- The new dialer and chat agent writes retry on 502/503/504 when they carry an `Idempotency-Key` (the API dedupes them).
- Webhooks: documented and tested the 24 h two-signature header during secret rotation.

## 0.3.0

- A method for every operation in the API spec (154/154), generated from `spec/openapi.json`.
- `webhooks.create_endpoint` gets an automatic `Idempotency-Key` and is retried.
