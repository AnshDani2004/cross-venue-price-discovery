"""Injectable public WebSocket transport boundary."""

from __future__ import annotations

import asyncio
from typing import Protocol, cast

import websockets

from cross_venue.collectors.exceptions import CollectorError


class TransportError(CollectorError):
    """Raised when a WebSocket frame cannot be safely consumed."""


class WebSocketConnection(Protocol):
    """Minimal connection protocol used by the live collector runtime."""

    async def send(self, message: str) -> None:
        """Send a text frame."""

    async def recv(self) -> str | bytes:
        """Receive one text or binary frame."""

    async def close(self) -> None:
        """Close the connection."""


class WebSocketConnector(Protocol):
    """Injectable connector for live and fake WebSocket transports."""

    async def connect(
        self,
        url: str,
        *,
        open_timeout_seconds: float,
        max_message_bytes: int,
    ) -> WebSocketConnection:
        """Open a WebSocket connection."""


class WebsocketsConnector:
    """Production connector backed by the ``websockets`` package."""

    async def connect(
        self,
        url: str,
        *,
        open_timeout_seconds: float,
        max_message_bytes: int,
    ) -> WebSocketConnection:
        connection = await websockets.connect(
            url,
            open_timeout=open_timeout_seconds,
            max_size=max_message_bytes,
        )
        return cast(WebSocketConnection, connection)


async def recv_with_timeout(
    connection: WebSocketConnection,
    *,
    receive_timeout_seconds: float,
) -> str | bytes:
    """Receive one frame with a bounded timeout."""

    try:
        return await asyncio.wait_for(connection.recv(), timeout=receive_timeout_seconds)
    except TimeoutError as exc:
        raise TransportError("receive timeout") from exc


def decode_text_frame(frame: str | bytes) -> str:
    """Decode text frames and reject invalid binary payloads explicitly."""

    if isinstance(frame, str):
        return frame
    try:
        return frame.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TransportError("binary WebSocket frame is not valid UTF-8 JSON") from exc
