import asyncio
import struct

HANGUP = 0x00
UUID_PACKET = 0x01
DTMF = 0x03
PCM_8K = 0x10
ERROR = 0xFF

class ProtocolError(ValueError):
    pass

def encode_packet(kind: int, payload: bytes = b'') -> bytes:
    if not 0 <= kind <= 255 or len(payload) > 65535:
        raise ProtocolError('Invalid frame size or type')
    return struct.pack('!BH', kind, len(payload)) + payload

async def read_packet(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    header = await reader.readexactly(3)
    kind, size = struct.unpack('!BH', header)
    payload = await reader.readexactly(size)
    if kind == UUID_PACKET and size != 16:
        raise ProtocolError('UUID must be 16 bytes')
    if kind == PCM_8K and size % 2:
        raise ProtocolError('PCM16 must have even byte length')
    if kind == HANGUP and size:
        raise ProtocolError('Hangup payload must be empty')
    return kind, payload
