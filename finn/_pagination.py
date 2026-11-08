"""Auto-pagination. The API has a few list styles, and the paginators hide them behind one iterator:

- cursor (new lists: agents, chat, approvals): ``?cursor=`` -> ``{data|approvals, next_cursor, has_more?}``
- offset (older voice lists: calls, finns, audiences, ...): ``?limit=&offset=`` -> ``{data, limit, offset, total?}``
- page (contacts): ``?page=&page_size=`` -> ``{contacts, page, totalPages}``
- before (cases, timeline): ``?before=`` -> ``{cases, next_before}`` or ``{items, next}``
- after (case events): ``?after=&limit=`` -> ``{events, next_after}``

    for call in finn.calls.list_all(status="completed"): ...
    for page in finn.calls.list_all().pages(): ...
    async for agent in async_finn.agents.list_all(): ...
"""
from __future__ import annotations

from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    Generic,
    Iterator,
    List,
    Optional,
    TypeVar,
)

T = TypeVar("T")
Query = Dict[str, Any]


class PageStrategy:
    """How one list style reads items and builds the next page's query."""

    def __init__(
        self,
        items: Callable[[Any], List[Any]],
        next_query: Callable[[Any, Query, int], Optional[Query]],
    ) -> None:
        self.items = items
        self.next_query = next_query


def _rec(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _arr(v: Any) -> List[Any]:
    return v if isinstance(v, list) else []


def _num(v: Any) -> Optional[int]:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def cursor_strategy(key: str = "data") -> PageStrategy:
    """``?cursor=`` lists answering ``{[key], next_cursor, has_more?}``."""

    def next_query(res: Any, query: Query, count: int) -> Optional[Query]:
        r = _rec(res)
        cursor = r.get("next_cursor")
        if r.get("has_more") is False or not isinstance(cursor, str) or cursor == "" or cursor == query.get("cursor"):
            return None
        return {**query, "cursor": cursor}

    return PageStrategy(lambda res: _arr(_rec(res).get(key)), next_query)


def offset_strategy(key: str = "data") -> PageStrategy:
    """``?limit=&offset=`` lists answering ``{data, limit, offset, total?}``."""

    def next_query(res: Any, query: Query, count: int) -> Optional[Query]:
        if count == 0:
            return None
        r = _rec(res)
        offset = _num(r.get("offset"))
        if offset is None:
            offset = int(query.get("offset") or 0)
        limit = _num(r.get("limit"))
        if limit is None:
            limit = int(query.get("limit") or count)
        next_offset = offset + count
        total = _num(r.get("total"))
        if total is not None and next_offset >= total:
            return None
        if count < limit:
            return None
        return {**query, "offset": next_offset}

    return PageStrategy(lambda res: _arr(_rec(res).get(key)), next_query)


def page_strategy(key: str) -> PageStrategy:
    """``?page=&page_size=`` lists answering ``{[key], page, totalPages}``."""

    def next_query(res: Any, query: Query, count: int) -> Optional[Query]:
        if count == 0:
            return None
        r = _rec(res)
        page = _num(r.get("page"))
        if page is None:
            page = int(query.get("page") or 1)
        total_pages = _num(r.get("totalPages"))
        if total_pages is not None and page >= total_pages:
            return None
        return {**query, "page": page + 1}

    return PageStrategy(lambda res: _arr(_rec(res).get(key)), next_query)


def before_strategy(key: str, next_key: str) -> PageStrategy:
    """``?before=`` lists answering ``{[key], [next_key]}``."""

    def next_query(res: Any, query: Query, count: int) -> Optional[Query]:
        nxt = _rec(res).get(next_key)
        if nxt is None or nxt == "" or str(nxt) == str(query.get("before", "")):
            return None
        return {**query, "before": nxt}

    return PageStrategy(lambda res: _arr(_rec(res).get(key)), next_query)


def after_strategy(key: str, next_key: str) -> PageStrategy:
    """``?after=`` lists answering ``{[key], [next_key]}``, where ``next_key`` is the last sequence number on the page."""

    def next_query(res: Any, query: Query, count: int) -> Optional[Query]:
        nxt = _num(_rec(res).get(next_key))
        if nxt is None or nxt == query.get("after"):
            return None
        limit = query.get("limit")
        if limit is not None and count < int(limit):
            return None
        return {**query, "after": nxt}

    return PageStrategy(lambda res: _arr(_rec(res).get(key)), next_query)


class SyncPaginator(Generic[T]):
    """Iterates every item of a list, fetching pages lazily."""

    def __init__(self, fetch_page: Callable[[Query], Any], strategy: PageStrategy, query: Optional[Query] = None):
        self._fetch_page = fetch_page
        self._strategy = strategy
        self._query: Query = {k: v for k, v in (query or {}).items() if v is not None}

    def pages(self) -> Iterator[Any]:
        """Each raw page response."""
        query: Optional[Query] = dict(self._query)
        while query is not None:
            res = self._fetch_page(query)
            yield res
            # An empty page ends the list only when the strategy finds no next page: the API filters some lists
            # after paging (hidden cases, chat notes), so a page can come back empty with a cursor that moves on.
            query = self._strategy.next_query(res, query, len(self._strategy.items(res)))

    def __iter__(self) -> Iterator[T]:
        for page in self.pages():
            yield from self._strategy.items(page)

    def to_list(self, limit: int = 10_000) -> List[T]:
        """Collects items into a list (stops at ``limit`` items)."""
        out: List[T] = []
        for item in self:
            out.append(item)
            if len(out) >= limit:
                break
        return out


class AsyncPaginator(Generic[T]):
    """Async version of SyncPaginator: ``async for item in paginator``."""

    def __init__(
        self, fetch_page: Callable[[Query], Awaitable[Any]], strategy: PageStrategy, query: Optional[Query] = None
    ):
        self._fetch_page = fetch_page
        self._strategy = strategy
        self._query: Query = {k: v for k, v in (query or {}).items() if v is not None}

    async def pages(self) -> AsyncIterator[Any]:
        """Each raw page response."""
        query: Optional[Query] = dict(self._query)
        while query is not None:
            res = await self._fetch_page(query)
            yield res
            # An empty page ends the list only when the strategy finds no next page: the API filters some lists
            # after paging (hidden cases, chat notes), so a page can come back empty with a cursor that moves on.
            query = self._strategy.next_query(res, query, len(self._strategy.items(res)))

    async def _items(self) -> AsyncIterator[T]:
        async for page in self.pages():
            for item in self._strategy.items(page):
                yield item

    def __aiter__(self) -> AsyncIterator[T]:
        return self._items()

    async def to_list(self, limit: int = 10_000) -> List[T]:
        """Collects items into a list (stops at ``limit`` items)."""
        out: List[T] = []
        async for item in self:
            out.append(item)
            if len(out) >= limit:
                break
        return out
