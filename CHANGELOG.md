# Changelog

## 0.4.0 (2026-11-08)

First release on PyPI since 0.2.0 (0.3.0 was tagged in the repo but never uploaded).

### Added

- Operations added to the API since 0.3.0, all live: `finn.webhooks.test_endpoint`, `redeliver_delivery`,
  `rotate_endpoint_secret`; `finn.agents.archive`; `finn.organization.get_usage`; `finn.dialer.mark_follow_up_done`,
  `set_call_disposition`, `add_call_note`; `finn.chat.get_agent`, `update_agent`, `test_agent`. The SDK covers 165 of
  165 operations.
- Case events page: `finn.cases.list_events(id, after=, limit=)` returns `{"events", "next_after"}`, and
  `finn.cases.list_all_events(id)` walks every page (new `after` strategy).
- `WebhookEvent` has the envelope's optional `event_id` (the dedupe key), `occurred_at` and `org_id`.
- Requests send `Finn-Version: 2026-11-01` by default (`DEFAULT_FINN_VERSION`; `version=None` sends none).

### Changed

- Spec refreshed: error responses use the nested `{"error": {"code", "message", ...}}` shape the API returns,
  `rotate_secret` takes an optional `Idempotency-Key`, case-event paging.
- Legacy error bodies that name fields as a string list (for example `unsupported_field`) now fill `FinnError.fields`.
- Retries: the waits of one request (backoff and `Retry-After`) add up to at most `max_retry_wait`, default 20 s;
  a retry that would go past it throws the last error instead.
- The new dialer and chat agent writes retry on 502/503/504 when they carry an `Idempotency-Key` (the API dedupes them).
- Webhooks: documented and tested the 24 h two-signature header during secret rotation.
- README: quickstart no longer reads `call_uuid` on the approval branch, test keys get `403 test_mode` on outward
  actions, full list of writes that can answer an approval hold, `pip install hirefinn`.

## 0.3.0 (not uploaded to PyPI)

- A method for every operation in the API spec (154/154), generated from `spec/openapi.json`.
- `webhooks.create_endpoint` gets an automatic `Idempotency-Key` and is retried.
