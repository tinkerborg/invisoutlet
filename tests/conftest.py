"""Shared fixtures and a fake aiohttp WebSocket for client tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import aiohttp
import pytest

from invisoutlet.client import InvisOutletClient


class FakeMessage:
    """Stand-in for an aiohttp WSMessage."""

    def __init__(self, mtype: aiohttp.WSMsgType, data: str) -> None:
        """Initialize the message."""
        self.type = mtype
        self.data = data


class FakeWebSocket:
    """In-memory double for aiohttp's ClientWebSocketResponse.

    On ``send_str`` it auto-replies with an envelope echoing the request's
    ``packetID``, using configurable ``responses`` (callbackArgs per callback),
    ``puback`` status, and a ``no_reply`` set of callbacks that send nothing.
    """

    def __init__(self) -> None:
        """Initialize the fake socket."""
        self._queue: asyncio.Queue[FakeMessage | None] = asyncio.Queue()
        self.sent: list[dict[str, Any]] = []
        self.closed = False
        self.responses: dict[int, Any] = {}
        self.puback: int = 1
        self.no_reply: set[int] = set()

    def __aiter__(self) -> AsyncIterator[FakeMessage]:
        """Iterate incoming messages."""
        return self

    async def __anext__(self) -> FakeMessage:
        """Return the next incoming message."""
        msg = await self._queue.get()
        if msg is None:
            raise StopAsyncIteration
        return msg

    async def send_str(self, data: str) -> None:
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
        self._queue.put_nowait(FakeMessage(aiohttp.WSMsgType.TEXT, json.dumps(response)))

    def push(self, message: dict[str, Any]) -> None:
        """Inject a server-initiated message that is not a reply."""
        self._queue.put_nowait(FakeMessage(aiohttp.WSMsgType.TEXT, json.dumps(message)))

    async def close(self) -> None:
        """Close the socket and unblock the reader."""
        self.closed = True
        self._queue.put_nowait(None)

    def exception(self) -> Exception | None:
        """Return the stored exception (none for the fake)."""
        return None


class FakeSession:
    """Minimal stand-in for aiohttp.ClientSession."""

    def __init__(self) -> None:
        """Initialize the fake session."""
        self.closed = False
        self._next_ws: list[FakeWebSocket] = []

    def queue_ws(self, ws: FakeWebSocket) -> None:
        """Queue a websocket to be handed out by the next ``ws_connect``."""
        self._next_ws.append(ws)

    async def ws_connect(self, url: str, **kwargs: object) -> FakeWebSocket:
        """Return the next queued websocket, or fail like a refused connection."""
        if not self._next_ws:
            raise aiohttp.ClientError("connection refused")
        return self._next_ws.pop(0)

    async def close(self) -> None:
        """Mark the session closed."""
        self.closed = True


@pytest.fixture
async def connected_client() -> AsyncIterator[tuple[InvisOutletClient, FakeWebSocket]]:
    """Yield a client wired to a fake WebSocket with its read loop running."""
    client = InvisOutletClient("device.local")
    ws = FakeWebSocket()
    client._ws = ws  # type: ignore[assignment]
    client._session = FakeSession()  # type: ignore[assignment]
    client._read_task = asyncio.create_task(client._read_loop())
    try:
        yield client, ws
    finally:
        await client.close()
