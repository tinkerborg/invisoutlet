"""Shared fixtures and an in-memory fake transport for client tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import aiohttp
import pytest

from invisoutlet.client import InvisOutletClient


class FakeMessage:
    """Stand-in for an aiohttp WSMessage (used by the WsTransport tests)."""

    def __init__(self, mtype: aiohttp.WSMsgType, data: str) -> None:
        """Initialize the message."""
        self.type = mtype
        self.data = data


class FakeTransport:
    """In-memory double for a client transport.

    Speaks the transport interface (``connect`` / ``send`` / async-iterate
    decoded ``dict`` messages / ``close``). On ``send`` it auto-replies with an
    envelope echoing the request's ``packetID``, using configurable ``responses``
    (callbackArgs per callback), ``puback`` status, and a ``no_reply`` set of
    callbacks that send nothing.
    """

    name = "fake"

    def __init__(self) -> None:
        """Initialize the fake transport."""
        self._queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self.sent: list[dict[str, Any]] = []
        self.closed = False
        self.responses: dict[int, Any] = {}
        self.puback: int = 1
        self.no_reply: set[int] = set()

    async def connect(self) -> None:
        """No-op: tests inject this transport directly."""

    async def send(self, data: str) -> None:
        """Record an outgoing request and enqueue the canned reply."""
        sent = json.loads(data)
        self.sent.append(sent)
        callback_name = sent["payload"]["callbackName"]
        if callback_name in self.no_reply:
            return
        response: dict[str, Any] = {
            "packetID": sent["packetID"],
            "PUBACK": self.puback,
            "payload": {"callbackName": callback_name},
        }
        if callback_name in self.responses:
            response["payload"]["callbackArgs"] = self.responses[callback_name]
        self._queue.put_nowait(response)

    def push(self, message: dict[str, Any]) -> None:
        """Inject a server-initiated message that is not a reply."""
        self._queue.put_nowait(message)

    def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        """Iterate incoming decoded messages."""
        return self

    async def __anext__(self) -> dict[str, Any]:
        """Return the next incoming message."""
        msg = await self._queue.get()
        if msg is None:
            raise StopAsyncIteration
        return msg

    async def close(self) -> None:
        """Close the transport and unblock the reader."""
        self.closed = True
        self._queue.put_nowait(None)


@pytest.fixture
async def connected_client() -> AsyncIterator[tuple[InvisOutletClient, FakeTransport]]:
    """Yield a client wired to a fake transport with its read loop running."""
    client = InvisOutletClient("device.local")
    transport = FakeTransport()
    client._transport = transport  # type: ignore[assignment]
    client._preferred_name = transport.name
    client._read_task = asyncio.create_task(client._read_loop())
    try:
        yield client, transport
    finally:
        await client.close()
