import asyncio
import pytest
from gateway.protocol import PCM_8K, UUID_PACKET, ProtocolError, encode_packet, read_packet

def parse(frame: bytes) -> tuple[int, bytes]:
    async def run():
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        reader.feed_eof()
        return await read_packet(reader)
    return asyncio.run(run())

def test_pcm_roundtrip():
    assert parse(encode_packet(PCM_8K, b'\x00\x00' * 160)) == (PCM_8K, b'\x00\x00' * 160)

def test_uuid():
    assert parse(encode_packet(UUID_PACKET, bytes(16))) == (UUID_PACKET, bytes(16))

def test_invalid_uuid():
    with pytest.raises(ProtocolError):
        parse(encode_packet(UUID_PACKET, b'x'))

def test_odd_pcm():
    with pytest.raises(ProtocolError):
        parse(encode_packet(PCM_8K, b'x'))

def test_truncated():
    with pytest.raises(asyncio.IncompleteReadError):
        parse(b'\x10\x00\x02\x00')
