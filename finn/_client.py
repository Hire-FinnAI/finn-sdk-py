"""The Finn API clients."""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Mapping, Optional

import httpx

from ._approval import ApprovalResult
from ._core import (
    DEFAULT_FINN_VERSION,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_RETRY_AFTER,
    DEFAULT_MAX_RETRY_WAIT,
    DEFAULT_TIMEOUT,
    AsyncCore,
    SyncCore,
)
from ._generated.request import AsyncTypedRequest, TypedRequest
from ._generated.resources import (
    Agents,
    Approvals,
    AsyncAgents,
    AsyncApprovals,
    AsyncAudiences,
    AsyncCalls,
    AsyncCases,
    AsyncChat,
    AsyncContacts,
    AsyncCrm,
    AsyncDeployments,
    AsyncDialer,
    AsyncDoNotCall,
    AsyncFinns,
    AsyncOrganization,
    AsyncPhoneNumbers,
    AsyncSales,
    AsyncVoices,
    AsyncWallet,
    AsyncWebhooks,
    Audiences,
    Calls,
    Cases,
    Chat,
    Contacts,
    Crm,
    Deployments,
    Dialer,
    DoNotCall,
    Finns,
    Organization,
    PhoneNumbers,
    Sales,
    Voices,
    Wallet,
    Webhooks,
)


class Finn(TypedRequest, SyncCore):
    """The Finn API client (sync).

        from finn import Finn
        finn = Finn()  # reads FINN_API_KEY
        calls = finn.calls.list(limit=10)

    Args:
        api_key: ``finn_live_...`` org key, ``finn_test_...`` test key, or an OAuth ``finn_oat_...`` token.
            Defaults to env FINN_API_KEY.
        base_url: Defaults to ``https://api.hirefinn.ai/v1``.
        org: Org to act in (Finn-Org header). Needed only for tokens that can use more than one org.
        version: Pins the API version (Finn-Version header), a date such as ``2026-11-01``. Defaults to
            ``DEFAULT_FINN_VERSION``, the version this SDK was built against; ``None`` sends no header.
        max_retries: Retries after the first attempt, on network errors, 408, 429, 502, 503 and 504. POST/PATCH are
            retried only with an Idempotency-Key on IDEMPOTENT_WRITE_ROUTES. Default 2.
        timeout: Timeout per attempt in seconds. Default 60.
        auto_idempotency: Send a generated Idempotency-Key on spending and outward writes (place a call, rent a
            number, deploy, start or send a chat, create an agent, start a case) when the caller did not pass one,
            so they can be retried safely. Default True.
        max_retry_after: Longest Retry-After (seconds) the SDK will wait out; a longer one raises instead. Default 60.
        max_retry_wait: Most seconds one request waits between its retries, Retry-After included; a retry that would
            go past it is not made and the last error is raised. Default 20.
        default_headers: Headers sent on every request.
        http_client: Your own httpx.Client (proxies, transports, tests). The SDK does not close it.
        sleep: Replaces the wait between retries (for tests).
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        org: Optional[str] = None,
        version: Optional[str] = DEFAULT_FINN_VERSION,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: float = DEFAULT_TIMEOUT,
        auto_idempotency: bool = True,
        max_retry_after: float = DEFAULT_MAX_RETRY_AFTER,
        max_retry_wait: float = DEFAULT_MAX_RETRY_WAIT,
        default_headers: Optional[Mapping[str, str]] = None,
        http_client: Optional[httpx.Client] = None,
        sleep: Optional[Callable[[float], None]] = None,
    ) -> None:
        super().__init__(
            api_key=api_key, base_url=base_url, org=org, version=version, max_retries=max_retries,
            timeout=timeout, auto_idempotency=auto_idempotency, max_retry_after=max_retry_after, max_retry_wait=max_retry_wait,
            default_headers=default_headers, http_client=http_client, sleep=sleep,
        )
        self.calls = Calls(self)
        self.finns = Finns(self)
        self.voices = Voices(self)
        self.phone_numbers = PhoneNumbers(self)
        self.audiences = Audiences(self)
        #: Campaigns: outbound and inbound deployments of a Finn.
        self.deployments = Deployments(self)
        self.wallet = Wallet(self)
        self.do_not_call = DoNotCall(self)
        #: CRM records (contacts and other record kinds).
        self.contacts = Contacts(self)
        self.cases = Cases(self)
        self.approvals = Approvals(self)
        self.agents = Agents(self)
        self.chat = Chat(self)
        #: CRM: records, stages, forms, documents, follow-ups, views and imports (/crm).
        self.crm = Crm(self)
        self.dialer = Dialer(self)
        #: Webhook endpoints, their deliveries, and the event types.
        self.webhooks = Webhooks(self)
        #: The organization, its members, integrations and API keys.
        self.organization = Organization(self)
        #: Experimental: the Sales API is switched off for every organization; calls answer an error until it is on
        #: for yours.
        self.sales = Sales(self)

    def __enter__(self) -> "Finn":
        return self

    def wait_for_approval(self, id: str, **kwargs: Any) -> ApprovalResult:
        """Polls an approval until it is decided (see ``approvals.wait``)."""
        return self.approvals.wait(id, **kwargs)


class AsyncFinn(AsyncTypedRequest, AsyncCore):
    """The Finn API client (async). Same options as Finn; ``http_client`` is an httpx.AsyncClient.

        from finn import AsyncFinn
        async with AsyncFinn() as finn:
            calls = await finn.calls.list(limit=10)
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        org: Optional[str] = None,
        version: Optional[str] = DEFAULT_FINN_VERSION,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: float = DEFAULT_TIMEOUT,
        auto_idempotency: bool = True,
        max_retry_after: float = DEFAULT_MAX_RETRY_AFTER,
        max_retry_wait: float = DEFAULT_MAX_RETRY_WAIT,
        default_headers: Optional[Mapping[str, str]] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        sleep: Optional[Callable[[float], Awaitable[None]]] = None,
    ) -> None:
        super().__init__(
            api_key=api_key, base_url=base_url, org=org, version=version, max_retries=max_retries,
            timeout=timeout, auto_idempotency=auto_idempotency, max_retry_after=max_retry_after, max_retry_wait=max_retry_wait,
            default_headers=default_headers, http_client=http_client, sleep=sleep,
        )
        self.calls = AsyncCalls(self)
        self.finns = AsyncFinns(self)
        self.voices = AsyncVoices(self)
        self.phone_numbers = AsyncPhoneNumbers(self)
        self.audiences = AsyncAudiences(self)
        self.deployments = AsyncDeployments(self)
        self.wallet = AsyncWallet(self)
        self.do_not_call = AsyncDoNotCall(self)
        self.contacts = AsyncContacts(self)
        self.cases = AsyncCases(self)
        self.approvals = AsyncApprovals(self)
        self.agents = AsyncAgents(self)
        self.chat = AsyncChat(self)
        #: CRM: records, stages, forms, documents, follow-ups, views and imports (/crm).
        self.crm = AsyncCrm(self)
        self.dialer = AsyncDialer(self)
        #: Webhook endpoints, their deliveries, and the event types.
        self.webhooks = AsyncWebhooks(self)
        #: The organization, its members, integrations and API keys.
        self.organization = AsyncOrganization(self)
        #: Experimental: the Sales API is switched off for every organization; calls answer an error until it is on
        #: for yours.
        self.sales = AsyncSales(self)

    async def __aenter__(self) -> "AsyncFinn":
        return self

    async def wait_for_approval(self, id: str, **kwargs: Any) -> ApprovalResult:
        """Polls an approval until it is decided (see ``approvals.wait``)."""
        return await self.approvals.wait(id, **kwargs)
