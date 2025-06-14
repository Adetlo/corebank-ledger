"""Correlation ids, request-size limits and access logging as pure ASGI middleware."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from uuid import uuid4

from corebank.logging import correlation_id_var

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

logger = logging.getLogger("corebank.access")
_SAFE_CID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return str(value.decode("latin-1"))
    return None


class CorrelationIdMiddleware:
    """Accept ``X-Correlation-ID`` (or ``X-Request-ID``) or mint one; echo it back."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = _header(scope, b"x-correlation-id") or _header(scope, b"x-request-id")
        cid = incoming if incoming and _SAFE_CID.match(incoming) else uuid4().hex
        token = correlation_id_var.set(cid)
        started = time.perf_counter()
        status_holder = {"status": 0}

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-correlation-id", cid.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "request",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": status_holder["status"],
                    "duration_ms": duration_ms,
                },
            )
            correlation_id_var.reset(token)


class RequestSizeLimitMiddleware:
    """Reject bodies larger than ``max_bytes`` with 413 before they are parsed."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            declared = _header(scope, b"content-length")
            if declared and declared.isdigit() and int(declared) > self.max_bytes:
                await self._reject(send)
                return
            received = 0
            rejected = False

            async def limited_receive() -> Message:
                nonlocal received, rejected
                message = await receive()
                if message["type"] == "http.request":
                    received += len(message.get("body", b""))
                    if received > self.max_bytes and not rejected:
                        # Answer 413 ourselves, then tell the app the client is gone.
                        rejected = True
                        await self._reject(send)
                        return {"type": "http.disconnect"}
                return message

            async def guarded_send(message: Message) -> None:
                if not rejected:
                    await send(message)

            await self.app(scope, limited_receive, guarded_send)
            return
        await self.app(scope, receive, send)

    async def _reject(self, send: Send) -> None:
        body = (
            b'{"error":{"code":"PAYLOAD_TOO_LARGE","message":"Request body exceeds the '
            b'configured limit.","correlation_id":"'
            + (correlation_id_var.get() or "").encode()
            + b'"}}'
        )
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
