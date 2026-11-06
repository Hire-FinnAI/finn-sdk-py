"""A recording mock transport, so the tests never touch the network."""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, Union

import httpx

from finn import AsyncFinn, Finn

Step = Union[Callable[[httpx.Request], httpx.Response], BaseException]


def json_(status: int, body: Any = None, headers: Optional[Dict[str, str]] = None) -> Step:
    """A step answering JSON (a fresh Response per call)."""

    def make(req: httpx.Request) -> httpx.Response:
        content = b"" if body is None else json.dumps(body).encode()
        return httpx.Response(status, content=content, headers={"content-type": "application/json", **(headers or {})})

    return make


def text_(status: int, text: str, content_type: str = "text/html") -> Step:
    return lambda req: httpx.Response(status, content=text.encode(), headers={"content-type": content_type})


class Recorder:
    """Answers each request with the next step (the last one repeats) and records what it was sent."""

    def __init__(self, steps: List[Step]):
        self.steps = steps
        self.calls: List[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.calls.append(request)
        step = self.steps[min(len(self.calls) - 1, len(self.steps) - 1)]
        if isinstance(step, BaseException):
            raise step
        return step(request)


def client(steps: List[Step], **options: Any):
    rec = Recorder(steps)
    sleeps: List[float] = []
    kwargs: Dict[str, Any] = {
        "api_key": "finn_live_test_key",
        "http_client": httpx.Client(transport=httpx.MockTransport(rec)),
        "sleep": sleeps.append,
    }
    kwargs.update(options)
    return Finn(**kwargs), rec.calls, sleeps


def async_client(steps: List[Step], **options: Any):
    rec = Recorder(steps)
    sleeps: List[float] = []

    async def sleep(s: float) -> None:
        sleeps.append(s)

    kwargs: Dict[str, Any] = {
        "api_key": "finn_live_test_key",
        "http_client": httpx.AsyncClient(transport=httpx.MockTransport(rec)),
        "sleep": sleep,
    }
    kwargs.update(options)
    return AsyncFinn(**kwargs), rec.calls, sleeps


def body_of(req: httpx.Request) -> Any:
    return json.loads(req.content.decode())
