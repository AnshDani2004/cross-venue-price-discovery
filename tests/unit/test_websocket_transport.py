import pytest

from cross_venue.collectors.transport import TransportError, decode_text_frame, recv_with_timeout


class FakeConnection:
    def __init__(self, frame: str | bytes) -> None:
        self.frame = frame
        self.closed = False

    async def send(self, message: str) -> None:
        self.sent = message

    async def recv(self) -> str | bytes:
        return self.frame

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_receive_returns_raw_frame_before_decode() -> None:
    connection = FakeConnection('{"type":"heartbeat"}')

    frame = await recv_with_timeout(connection, receive_timeout_seconds=1)

    assert frame == '{"type":"heartbeat"}'


def test_decode_text_frame_accepts_text_and_utf8_binary() -> None:
    assert decode_text_frame("hello") == "hello"
    assert decode_text_frame(b"hello") == "hello"


def test_decode_text_frame_rejects_invalid_utf8_binary() -> None:
    with pytest.raises(TransportError, match="UTF-8"):
        decode_text_frame(b"\xff")
