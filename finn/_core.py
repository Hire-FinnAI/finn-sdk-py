"""The HTTP core shared by Finn and AsyncFinn: auth, headers, retries, Idempotency-Key, errors."""
from __future__ import annotations

import asyncio
import datetime as _dt
import json
import os
import random
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Tuple, Union
from urllib.parse import quote, urlencode

import httpx

from ._approval import PendingApproval, looks_pending
from ._errors import FinnConnectionError, FinnError, FinnSdkError, FinnTimeoutError
from ._types import FinnResponse
from ._version import __version__

DEFAULT_BASE_URL = "https://api.hirefinn.ai/v1"
DEFAULT_MAX_RETRIES = 2
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRY_AFTER = 60.0

#: Writes that get an automatic Idempotency-Key (when auto_idempotency is on). Mirrors finn-sdk-ts.
AUTO_IDEMPOTENCY_ROUTES = frozenset(
    {
        "post /calls",
        "post /phone_numbers",
        "post /deployments",
        "post /deployments/inbound",
        "post /chat/conversations",
        "post /chat/conversations/{id}/messages",
        "post /agents",
        "post /agents/{id}/cases",
        "post /webhook_endpoints",
    }
)

#: POST/PATCH routes where the API dedupes by Idempotency-Key (a retry with the same key and body replays the first
#: answer). Only these writes are retried, and only when they carry a key: other routes ignore the header, so a retry
#: after a timeout could create a second resource. ``*`` matches the rest of the path. Mirrors finn-sdk-ts.
IDEMPOTENT_WRITE_ROUTES: Tuple[str, ...] = (
    "post /calls",
    "post /phone_numbers",
    "post /deployments",
    "post /deployments/inbound",
    "post /chat/conversations",
    "post /chat/conversations/{id}/messages",
    "post /agents",
    "post /agents/{id}/cases",
    "post /crm/*",
    "patch /crm/*",
    "post /sales/plays/{slug}/run",
    "post /sales/drafts/{id}/skip",
    "post /webhook_endpoints",
)


def _route_matcher(route: str) -> Tuple[str, "re.Pattern[str]"]:
    method, path = route.split(" ", 1)
    parts = []
    for seg in path.split("/"):
        if seg == "*":
            parts.append(".+")
        elif re.fullmatch(r"\{[^}]+\}", seg):
            parts.append("[^/]+")
        else:
            parts.append(re.escape(seg))
    return method.upper(), re.compile("^" + "/".join(parts) + "/?$")


_IDEMPOTENT_WRITE_MATCHERS = [_route_matcher(r) for r in IDEMPOTENT_WRITE_ROUTES]


def honours_idempotency_key(method: str, path: str) -> bool:
    """True when the API dedupes this write by Idempotency-Key. ``path`` may be a template or a filled-in path."""
    m = method.upper()
    p = path.split("?", 1)[0]
    return any(m == mm and rx.match(p) for mm, rx in _IDEMPOTENT_WRITE_MATCHERS)


_SAFE_TO_RETRY_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})
_RETRY_BASE_DELAY = 0.5
_RETRY_MAX_DELAY = 8.0
_PATH_SAFE = "!~*'()"  # what encodeURIComponent leaves alone, besides -_.


def idempotency_key() -> str:
    """A new random Idempotency-Key (a UUID v4)."""
    return str(uuid.uuid4())


_new_key = idempotency_key


def _backoff(attempt: int) -> float:
    base = min(_RETRY_MAX_DELAY, _RETRY_BASE_DELAY * (2**attempt))
    return round(base * (1 - random.random() * 0.25), 3)


def _is_retryable(error: FinnError) -> bool:
    if error.status in (408, 429):
        return True
    if error.status == 409:
        return error.code == "idempotency_in_progress"
    # Not 500: a server error is usually not transient, and the write may already have happened.
    return error.status in (502, 503, 504)


def _query_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return ",".join(_query_value(x) for x in v)
    return str(v)


def _read_body(response: httpx.Response) -> Any:
    if response.status_code in (204, 205):
        return None
    text = response.text
    if text == "":
        return None
    ctype = response.headers.get("content-type", "")
    if "json" in ctype or re.match(r"^\s*[\[{]", text):
        try:
            return json.loads(text)
        except ValueError:
            return text
    return text


@dataclass
class _Prepared:
    method: str
    url: str
    headers: Dict[str, str]
    content: Optional[bytes]
    data: Any
    files: Optional[Mapping[str, Any]]
    max_retries: int
    timeout: float


class BaseCore:
    """Settings and request building shared by the sync and async cores."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        org: Optional[str] = None,
        version: Optional[str] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: float = DEFAULT_TIMEOUT,
        auto_idempotency: bool = True,
        max_retry_after: float = DEFAULT_MAX_RETRY_AFTER,
        default_headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        key = api_key if api_key is not None else os.environ.get("FINN_API_KEY")
        if not key:
            raise FinnSdkError("Missing API key: pass api_key= to Finn() or set FINN_API_KEY.")
        self._api_key = key
        #: Base URL, without a trailing slash.
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        #: Org to act in (Finn-Org header), for tokens that can use more than one org.
        self.org = org
        #: Pinned API version (Finn-Version header), a date such as ``2026-11-01``.
        self.version = version
        self.max_retries = max_retries
        self.timeout = timeout
        self.auto_idempotency = auto_idempotency
        self.max_retry_after = max_retry_after
        self._default_headers = dict(default_headers or {})

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self.base_url!r}, org={self.org!r}, version={self.version!r})"

    def build_url(
        self, path: str, path_params: Optional[Mapping[str, Any]] = None, query: Optional[Mapping[str, Any]] = None
    ) -> str:
        """Base URL + path with ``{name}`` filled in + query string."""

        def fill(match: "re.Match[str]") -> str:
            name = match.group(1)
            value = (path_params or {}).get(name)
            if value is None or value == "":
                raise FinnSdkError(f'Missing path parameter "{name}" for {path}')
            return quote(str(value), safe=_PATH_SAFE)

        filled = re.sub(r"\{([^}]+)\}", fill, path)
        pairs: List[Tuple[str, str]] = [(k, _query_value(v)) for k, v in (query or {}).items() if v is not None]
        qs = urlencode(pairs)
        sep = "" if filled.startswith("/") else "/"
        return f"{self.base_url}{sep}{filled}{'?' + qs if qs else ''}"

    def _prepare(
        self,
        method: str,
        path: str,
        *,
        path_params: Optional[Mapping[str, Any]] = None,
        query: Optional[Mapping[str, Any]] = None,
        body: Any = None,
        files: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, Optional[str]]] = None,
        idempotency_key: Union[str, bool, None] = None,
        org: Optional[str] = None,
        version: Optional[str] = None,
        max_retries: Optional[int] = None,
        timeout: Optional[float] = None,
        extra_headers: Optional[Mapping[str, str]] = None,
    ) -> _Prepared:
        upper = method.upper()
        route = f"{method.lower()} {path}"
        url = self.build_url(path, path_params, query)

        key: Optional[str] = None
        if isinstance(idempotency_key, str):
            key = idempotency_key
        elif idempotency_key is not False and self.auto_idempotency and route in AUTO_IDEMPOTENCY_ROUTES:
            key = _new_key()

        h: Dict[str, str] = {"Accept": "application/json", "User-Agent": f"finn-python/{__version__}"}
        h.update(self._default_headers)
        if org or self.org:
            h["Finn-Org"] = org or self.org  # type: ignore[assignment]
        if version or self.version:
            h["Finn-Version"] = version or self.version  # type: ignore[assignment]
        if key:
            h["Idempotency-Key"] = key
        for k, v in (headers or {}).items():
            if v is not None:
                h[k] = v

        content: Optional[bytes] = None
        data: Any = None
        if files:
            data = body
        elif body is not None:
            h["Content-Type"] = "application/json"
            content = json.dumps(body, default=_json_default).encode("utf-8")

        for k, v in (extra_headers or {}).items():
            h[k] = v
        # Authorization always wins over extra_headers.
        for k in [k for k in h if k.lower() == "authorization"]:
            del h[k]
        h["Authorization"] = f"Bearer {self._api_key}"

        has_key = any(k.lower() == "idempotency-key" for k in h)
        # Idempotent methods always; a POST/PATCH only with a key on a route that dedupes by it.
        can_retry = upper in _SAFE_TO_RETRY_METHODS or (has_key and honours_idempotency_key(upper, path))
        retries = max(0, self.max_retries if max_retries is None else max_retries) if can_retry else 0
        return _Prepared(
            method=upper,
            url=url,
            headers=h,
            content=content,
            data=data,
            files=files,
            max_retries=retries,
            timeout=self.timeout if timeout is None else timeout,
        )

    @staticmethod
    def _httpx_timeout(seconds: float) -> Optional[httpx.Timeout]:
        return httpx.Timeout(seconds) if seconds and seconds > 0 else None

    @staticmethod
    def _wrap_transport_error(err: Exception, timeout: float) -> FinnConnectionError:
        if isinstance(err, httpx.TimeoutException):
            return FinnTimeoutError(f"The request timed out after {timeout} s.")
        return FinnConnectionError(f"Could not reach the Finn API: {err}")

    def _finish(self, response: httpx.Response) -> Union[FinnResponse[Any], FinnError]:
        parsed = _read_body(response)
        if response.is_success:
            data: Any = parsed
            if response.status_code == 202 and looks_pending(parsed):
                data = PendingApproval.from_body(parsed)
            return FinnResponse(
                data=data,
                status=response.status_code,
                headers=response.headers,
                request_id=response.headers.get("x-request-id"),
                idempotent_replayed=response.headers.get("idempotent-replayed") == "true",
            )
        return FinnError.from_response(response.status_code, response.headers, parsed, response.reason_phrase)

    def _retry_wait(self, error: FinnError, attempt: int) -> Optional[float]:
        """Seconds to wait before retrying, or None to raise now."""
        if not _is_retryable(error):
            return None
        wait = float(error.retry_after) if error.retry_after is not None else _backoff(attempt)
        if wait > self.max_retry_after:
            return None
        return wait


def _json_default(v: Any) -> Any:
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.isoformat()
    raise TypeError(f"Object of type {type(v).__name__} is not JSON serializable")


class SyncCore(BaseCore):
    """Sync HTTP core (httpx.Client)."""

    def __init__(
        self,
        *,
        http_client: Optional[httpx.Client] = None,
        sleep: Optional[Callable[[float], None]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client()
        self._sleep = sleep or time.sleep

    def close(self) -> None:
        """Closes the underlying httpx.Client (only when the SDK created it)."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "SyncCore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def request_with_response(self, method: str, path: str, **kwargs: Any) -> FinnResponse[Any]:
        """Any request, untyped (for endpoints newer than this SDK's spec), with status, headers and request id.

        kwargs: path_params, query, body, files, headers, idempotency_key, org, version, max_retries, timeout,
        extra_headers.
        """
        p = self._prepare(method, path, **kwargs)
        attempt = 0
        while True:
            try:
                response = self._client.request(
                    p.method, p.url, headers=p.headers, content=p.content, data=p.data, files=p.files,
                    timeout=self._httpx_timeout(p.timeout),
                )
            except httpx.TransportError as err:
                wrapped = self._wrap_transport_error(err, p.timeout)
                if attempt < p.max_retries:
                    self._sleep(_backoff(attempt))
                    attempt += 1
                    continue
                raise wrapped from err
            result = self._finish(response)
            if isinstance(result, FinnResponse):
                return result
            wait = self._retry_wait(result, attempt) if attempt < p.max_retries else None
            if wait is None:
                raise result
            self._sleep(wait)
            attempt += 1

    raw_request = request_with_response

    def _request_data(self, method: str, path: str, **kwargs: Any) -> Any:
        return self.request_with_response(method, path, **kwargs).data


class AsyncCore(BaseCore):
    """Async HTTP core (httpx.AsyncClient)."""

    def __init__(
        self,
        *,
        http_client: Optional[httpx.AsyncClient] = None,
        sleep: Optional[Callable[[float], Awaitable[None]]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient()
        self._sleep = sleep or asyncio.sleep

    async def close(self) -> None:
        """Closes the underlying httpx.AsyncClient (only when the SDK created it)."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "AsyncCore":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def request_with_response(self, method: str, path: str, **kwargs: Any) -> FinnResponse[Any]:
        """Async request_with_response(); see SyncCore.request_with_response."""
        p = self._prepare(method, path, **kwargs)
        attempt = 0
        while True:
            try:
                response = await self._client.request(
                    p.method, p.url, headers=p.headers, content=p.content, data=p.data, files=p.files,
                    timeout=self._httpx_timeout(p.timeout),
                )
            except httpx.TransportError as err:
                wrapped = self._wrap_transport_error(err, p.timeout)
                if attempt < p.max_retries:
                    await self._sleep(_backoff(attempt))
                    attempt += 1
                    continue
                raise wrapped from err
            result = self._finish(response)
            if isinstance(result, FinnResponse):
                return result
            wait = self._retry_wait(result, attempt) if attempt < p.max_retries else None
            if wait is None:
                raise result
            await self._sleep(wait)
            attempt += 1

    raw_request = request_with_response

    async def _request_data(self, method: str, path: str, **kwargs: Any) -> Any:
        return (await self.request_with_response(method, path, **kwargs)).data
