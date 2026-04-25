"""Tiny test-only fallback for the external ``aioresponses`` package.

This repo's tests only need queued ``GET`` responses with status/payload/body/exception,
so we provide a lightweight compatible context manager to avoid a hard dependency
in constrained CI environments.
"""
from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch


@dataclass
class _QueuedResponse:
    status: int = 200
    payload: Any = None
    body: bytes | str | None = None
    exception: Exception | None = None
    headers: dict[str, str] | None = None


class _FakeStream:
    def __init__(self, raw: bytes):
        self._raw = raw

    async def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            return self._raw
        return self._raw[:n]


class _FakeResponse:
    def __init__(self, spec: _QueuedResponse):
        self.status = spec.status
        self.headers = spec.headers or {}
        if spec.payload is not None:
            raw = json.dumps(spec.payload).encode("utf-8")
        elif isinstance(spec.body, str):
            raw = spec.body.encode("utf-8")
        elif spec.body is None:
            raw = b""
        else:
            raw = spec.body
        self.content = _FakeStream(raw)

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class aioresponses:
    def __init__(self):
        self._queue: dict[tuple[str, str], deque[_QueuedResponse]] = defaultdict(deque)
        self._patcher = None

    def get(
        self,
        url: str,
        *,
        payload: Any = None,
        body: bytes | str | None = None,
        status: int = 200,
        exception: Exception | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._queue[("GET", str(url))].append(
            _QueuedResponse(
                status=status,
                payload=payload,
                body=body,
                exception=exception,
                headers=headers,
            )
        )

    async def _mocked_request(self, method: str, url: str, **kwargs):
        key = (method.upper(), str(url))
        if key not in self._queue or not self._queue[key]:
            raise AssertionError(f"No queued mocked response for {method} {url}")

        spec = self._queue[key].popleft()
        if spec.exception is not None:
            raise spec.exception

        return _FakeResponse(spec)

    def __enter__(self):
        async def _patched_request(session, method: str, url: str, **kwargs):
            return await self._mocked_request(method, url, **kwargs)

        self._patcher = patch("aiohttp.client.ClientSession._request", new=_patched_request)
        self._patcher.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._patcher is not None:
            self._patcher.stop()
            self._patcher = None
        return False
