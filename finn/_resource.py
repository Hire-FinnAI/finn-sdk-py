"""Base classes for the generated resources."""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from ._approval import unwrap_approval
from ._core import AsyncCore, SyncCore
from ._pagination import AsyncPaginator, PageStrategy, SyncPaginator


def _clean(d: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    return {k: v for k, v in (d or {}).items() if v is not None}


class Resource:
    def __init__(self, core: SyncCore) -> None:
        self._core = core

    def _do(self, method: str, path: str, *, unwrap: bool = False, **kwargs: Any) -> Any:
        kwargs["query"] = _clean(kwargs.get("query"))
        data = self._core._request_data(method, path, **kwargs)
        return unwrap_approval(data) if unwrap else data

    def _pager(
        self, path: str, strategy: PageStrategy, *, path_params: Mapping[str, Any], query: Mapping[str, Any],
        **options: Any,
    ) -> SyncPaginator[Any]:
        return SyncPaginator(
            lambda q: self._core._request_data("get", path, path_params=path_params, query=q, **options),
            strategy,
            _clean(query),
        )


class AsyncResource:
    def __init__(self, core: AsyncCore) -> None:
        self._core = core

    async def _do(self, method: str, path: str, *, unwrap: bool = False, **kwargs: Any) -> Any:
        kwargs["query"] = _clean(kwargs.get("query"))
        data = await self._core._request_data(method, path, **kwargs)
        return unwrap_approval(data) if unwrap else data

    def _pager(
        self, path: str, strategy: PageStrategy, *, path_params: Mapping[str, Any], query: Mapping[str, Any],
        **options: Any,
    ) -> AsyncPaginator[Any]:
        return AsyncPaginator(
            lambda q: self._core._request_data("get", path, path_params=path_params, query=q, **options),
            strategy,
            _clean(query),
        )
