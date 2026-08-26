"""Wire transports for :class:`~invisoutlet.client.InvisOutletClient`.

Two device transports share one tiny interface — ``connect()``, ``send(str)``,
async-iterate decoded JSON ``dict`` messages, ``close()``:

* :class:`TcpTransport` — revB firmware serves the callback protocol as a raw
  TCP line protocol on port 3333: each request is JSON followed by ``\\n``, and
  the device streams back bare JSON objects, sometimes several packed into one
  TCP segment (so message boundaries are recovered by decoding, not by frame).
* :class:`WsTransport` — revA firmware serves the same protocol over a
  WebSocket on port 80 (``ws://host:80/ws``), one JSON object per text frame.

The client tries TCP first and falls back to the WebSocket, so both device
generations work behind the same high-level API.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from collections import deque
from typing import Any

import aiohttp

from .exceptions import InvisOutletConnectionError, InvisOutletTimeoutError

_LOGGER = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 10.0
_READ_CHUNK = 4096

# WebSocket ping interval (seconds). Lets aiohttp detect a silently-dropped
# connection (e.g. the device rebooting) instead of waiting forever for data.
_WS_HEARTBEAT = 10.0

# TCP keepalive tuning: after _KEEPALIVE_IDLE seconds of silence, probe every
# _KEEPALIVE_INTERVAL seconds, and give up after _KEEPALIVE_COUNT unanswered
# probes (erroring the pending read). Without this, a router dropping
# connection state mid-flight (e.g. a gateway reboot) leaves the socket
# half-open: it delivers nothing, never errors, and the read blocks forever.
# ~30s total to declare the peer dead.
_KEEPALIVE_IDLE = 15
_KEEPALIVE_INTERVAL = 5
_KEEPALIVE_COUNT = 3

# The idle knob is TCP_KEEPIDLE on Linux/Windows but TCP_KEEPALIVE on macOS;
# resolve whichever this platform has (None: use the platform default timing).
_TCP_IDLE_OPT = getattr(socket, "TCP_KEEPIDLE", None) or getattr(
    socket, "TCP_KEEPALIVE", None
)


def _enable_keepalive(sock: socket.socket) -> None:
    """Turn on TCP keepalive with our timing on a connected socket."""
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    for opt, value in (
        (_TCP_IDLE_OPT, _KEEPALIVE_IDLE),
        (getattr(socket, "TCP_KEEPINTVL", None), _KEEPALIVE_INTERVAL),
        (getattr(socket, "TCP_KEEPCNT", None), _KEEPALIVE_COUNT),
    ):
        if opt is not None:
            sock.setsockopt(socket.IPPROTO_TCP, opt, value)


class TcpTransport:
    """revB raw-TCP line protocol: ``json + "\\n"`` out, decoded dicts in."""

    name = "tcp"

    def __init__(self, host: str, port: int = 3333) -> None:
        """Initialize the transport (does not connect)."""
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._buf = ""
        self._pending: deque[dict[str, Any]] = deque()
        self._decoder = json.JSONDecoder()

    async def connect(self) -> None:
        """Open the TCP connection. Raises on failure."""
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=_CONNECT_TIMEOUT,
            )
        except TimeoutError as err:
            raise InvisOutletTimeoutError(
                f"Timeout connecting to {self.host}:{self.port} (tcp)"
            ) from err
        except OSError as err:
            raise InvisOutletConnectionError(
                f"Cannot connect to {self.host}:{self.port} (tcp): {err}"
            ) from err
        assert self._writer is not None
        sock = self._writer.get_extra_info("socket")
        if sock is not None:
            try:
                _enable_keepalive(sock)
            except OSError as err:
                _LOGGER.warning(
                    "Could not enable TCP keepalive for %s: %s", self.host, err
                )

    async def send(self, message: str) -> None:
        """Send one JSON message, newline-terminated."""
        if self._writer is None:
            raise InvisOutletConnectionError("Not connected")
        self._writer.write(message.encode() + b"\n")
        await self._writer.drain()

    def __aiter__(self) -> TcpTransport:
        """Iterate decoded JSON messages."""
        return self

    async def __anext__(self) -> dict[str, Any]:
        """Return the next decoded JSON object, reading more bytes as needed."""
        assert self._reader is not None
        while not self._pending:
            chunk = await self._reader.read(_READ_CHUNK)
            if not chunk:
                raise StopAsyncIteration  # EOF: device closed the connection
            self._buf += chunk.decode(errors="replace")
            self._drain_buffer()
        return self._pending.popleft()

    def _drain_buffer(self) -> None:
        """Pull every whole JSON object out of the buffer into ``_pending``.

        Objects may be separated by newlines/whitespace, packed back-to-back, or
        split across reads — ``raw_decode`` handles all three; a partial trailing
        object stays buffered until the rest arrives.
        """
        while True:
            self._buf = self._buf.lstrip()
            if not self._buf:
                break
            try:
                obj, end = self._decoder.raw_decode(self._buf)
            except json.JSONDecodeError:
                break  # partial trailing object; wait for more bytes
            self._buf = self._buf[end:]
            if isinstance(obj, dict):
                self._pending.append(obj)
            else:
                _LOGGER.warning("Ignoring non-object JSON on tcp: %r", obj)

    async def close(self) -> None:
        """Close the connection."""
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except (OSError, asyncio.CancelledError):
                pass
            self._writer = None
        self._reader = None


class WsTransport:
    """revA WebSocket protocol: one JSON object per text frame."""

    name = "ws"

    def __init__(self, host: str, port: int = 80) -> None:
        """Initialize the transport (does not connect)."""
        self.host = host
        self.port = port
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None

    async def connect(self) -> None:
        """Open the WebSocket (creating the session if needed). Raises on failure."""
        if self._session is None:
            self._session = aiohttp.ClientSession()
        try:
            self._ws = await asyncio.wait_for(
                self._session.ws_connect(
                    f"ws://{self.host}:{self.port}/ws", heartbeat=_WS_HEARTBEAT
                ),
                timeout=_CONNECT_TIMEOUT,
            )
        except TimeoutError as err:
            raise InvisOutletTimeoutError(
                f"Timeout connecting to {self.host}:{self.port} (ws)"
            ) from err
        except (OSError, aiohttp.ClientError) as err:
            raise InvisOutletConnectionError(
                f"Cannot connect to {self.host}:{self.port} (ws): {err}"
            ) from err

    async def send(self, message: str) -> None:
        """Send one JSON message as a text frame."""
        if self._ws is None:
            raise InvisOutletConnectionError("Not connected")
        await self._ws.send_str(message)

    def __aiter__(self) -> WsTransport:
        """Iterate decoded JSON messages."""
        return self

    async def __anext__(self) -> dict[str, Any]:
        """Return the next decoded text frame; stop on error/close."""
        assert self._ws is not None
        while True:
            msg = await self._ws.receive()
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    return json.loads(msg.data)
                except json.JSONDecodeError:
                    _LOGGER.warning("Received invalid JSON: %s", msg.data[:200])
                    continue
            if msg.type == aiohttp.WSMsgType.ERROR:
                _LOGGER.error("WebSocket error: %s", self._ws.exception())
                raise StopAsyncIteration
            if msg.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.CLOSED,
            ):
                _LOGGER.debug("WebSocket closed by device")
                raise StopAsyncIteration
            # BINARY / PING / PONG etc.: ignore and wait for the next frame.

    async def close(self) -> None:
        """Close the WebSocket and its session."""
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        if self._session is not None:
            await self._session.close()
            self._session = None
