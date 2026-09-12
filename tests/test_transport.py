"""Tests for the wire transports and the client's transport selection."""

from __future__ import annotations

import asyncio
import socket
from typing import Any

import aiohttp
import pytest

from invisoutlet import InvisOutletClient, InvisOutletConnectionError
from invisoutlet.transport import _TCP_IDLE_OPT, TcpTransport, WsTransport

from .conftest import FakeMessage, FakeTransport

# --- TcpTransport: newline / back-to-back / split reassembly ---------------


class _FakeReader:
    """StreamReader double that hands out queued byte chunks, then EOF."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    async def read(self, _n: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


class _FakeWriter:
    """StreamWriter double that records written bytes."""

    def __init__(self) -> None:
        self.buf = bytearray()

    def write(self, data: bytes) -> None:
        self.buf += data

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass


_OBJ1 = '{"packetID":1,"payload":{"callbackName":9}}'
_OBJ2 = '{"packetID":2,"payload":{"callbackName":10}}'
_OBJ3 = '{"packetID":3,"payload":{"callbackName":12}}'


async def test_tcp_reassembles_newline_and_backtoback() -> None:
    """Objects split by newline AND packed back-to-back in one chunk both decode."""
    transport = TcpTransport("device.local")
    transport._reader = _FakeReader(  # type: ignore[assignment]
        [
            (_OBJ1 + "\n").encode(),  # newline-delimited
            (_OBJ2 + _OBJ3).encode(),  # two objects, one chunk, no delimiter
        ]
    )
    got = [msg["packetID"] async for msg in transport]
    assert got == [1, 2, 3]


async def test_tcp_reassembles_object_split_across_reads() -> None:
    """An object split across two reads is buffered until complete."""
    transport = TcpTransport("device.local")
    mid = len(_OBJ1) // 2
    transport._reader = _FakeReader(  # type: ignore[assignment]
        [_OBJ1[:mid].encode(), _OBJ1[mid:].encode() + b"\n"]
    )
    got = [msg["packetID"] async for msg in transport]
    assert got == [1]


async def test_tcp_skips_non_object_json() -> None:
    """A stray non-object JSON value is ignored; following objects still decode."""
    transport = TcpTransport("device.local")
    transport._reader = _FakeReader([b"5\n" + _OBJ1.encode() + b"\n"])  # type: ignore[assignment]
    got = [msg["packetID"] async for msg in transport]
    assert got == [1]


async def test_tcp_send_appends_newline() -> None:
    """Outgoing messages are newline-terminated."""
    transport = TcpTransport("device.local")
    writer = _FakeWriter()
    transport._writer = writer  # type: ignore[assignment]
    await transport.send('{"x":1}')
    assert bytes(writer.buf) == b'{"x":1}\n'


async def test_tcp_send_without_connect_raises() -> None:
    """Sending before connect is an error, not a crash."""
    transport = TcpTransport("device.local")
    with pytest.raises(InvisOutletConnectionError):
        await transport.send("{}")


async def test_tcp_connect_enables_keepalive() -> None:
    """A connected socket has TCP keepalive on with our probe timing.

    Without keepalive, a router dropping connection state (e.g. a gateway
    reboot) leaves the socket half-open and the read blocked forever.
    """
    server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    transport = TcpTransport("127.0.0.1", port)
    try:
        await transport.connect()
        sock = transport._writer.get_extra_info("socket")  # type: ignore[union-attr]
        # Nonzero == enabled (BSD returns the flag's bit value, not 1).
        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) != 0
        if _TCP_IDLE_OPT is not None:
            assert sock.getsockopt(socket.IPPROTO_TCP, _TCP_IDLE_OPT) == 15
    finally:
        await transport.close()
        server.close()
        await server.wait_closed()


# --- WsTransport: frame typing -------------------------------------------


class _FakeWs:
    """ClientWebSocketResponse double driven by a queue of FakeMessages."""

    def __init__(self, messages: list[FakeMessage]) -> None:
        self._messages = list(messages)

    async def receive(self) -> FakeMessage:
        if self._messages:
            return self._messages.pop(0)
        return FakeMessage(aiohttp.WSMsgType.CLOSED, "")

    def exception(self) -> Exception | None:
        return None

    async def close(self) -> None:
        pass


async def test_ws_yields_text_and_skips_invalid_json() -> None:
    """Text frames decode to dicts; invalid JSON is skipped, not fatal."""
    transport = WsTransport("device.local")
    transport._ws = _FakeWs(  # type: ignore[assignment]
        [
            FakeMessage(aiohttp.WSMsgType.TEXT, "{not json"),
            FakeMessage(aiohttp.WSMsgType.TEXT, '{"packetID":1}'),
            FakeMessage(aiohttp.WSMsgType.CLOSE, ""),
        ]
    )
    got = [msg async for msg in transport]
    assert [m["packetID"] for m in got] == [1]


@pytest.mark.parametrize(
    "mtype",
    [aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED],
)
async def test_ws_stops_on_control_frame(mtype: aiohttp.WSMsgType) -> None:
    """An error/close frame stops iteration cleanly."""
    transport = WsTransport("device.local")
    transport._ws = _FakeWs([FakeMessage(mtype, "")])  # type: ignore[assignment]
    got = [msg async for msg in transport]
    assert got == []


# --- client transport selection: TCP first, WS fallback -------------------


async def test_connect_prefers_tcp(monkeypatch: pytest.MonkeyPatch) -> None:
    """When TCP connects, the WebSocket is never opened."""
    tcp = FakeTransport()
    tcp.name = "tcp"
    monkeypatch.setattr("invisoutlet.client.TcpTransport", lambda *a, **k: tcp)

    class _NoConnectWs:
        name = "ws"

        def __init__(self, *_a: Any, **_k: Any) -> None:
            pass

        async def connect(self) -> None:
            raise AssertionError("WsTransport.connect should not be called")

        async def close(self) -> None:
            pass

    monkeypatch.setattr("invisoutlet.client.WsTransport", _NoConnectWs)

    client = InvisOutletClient("device.local")
    await client.connect()
    assert client._transport is tcp
    assert client._preferred_name == "tcp"
    await client.close()


async def test_connect_falls_back_to_ws(monkeypatch: pytest.MonkeyPatch) -> None:
    """When TCP is refused, the client falls back to the WebSocket."""

    class _RefusingTcp:
        name = "tcp"

        def __init__(self, *_a: Any, **_k: Any) -> None:
            pass

        async def connect(self) -> None:
            raise InvisOutletConnectionError("refused")

        async def close(self) -> None:
            pass

    ws = FakeTransport()
    ws.name = "ws"
    monkeypatch.setattr("invisoutlet.client.TcpTransport", _RefusingTcp)
    monkeypatch.setattr("invisoutlet.client.WsTransport", lambda *a, **k: ws)

    client = InvisOutletClient("device.local")
    await client.connect()
    assert client._transport is ws
    assert client._preferred_name == "ws"
    await client.close()
