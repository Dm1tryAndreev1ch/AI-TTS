import asyncio
import pytest
from gateway.audiosocket import Connection
from gateway.protocol import DTMF, HANGUP, PCM_8K, UUID_PACKET, ProtocolError, encode_packet, read_packet
from gateway.server import AudioSocketServer, ServerSettings

UID = bytes(range(16))
PCM = b"\x01\x00" * 160


def run(coro):
    return asyncio.run(coro)


def parse(frame):
    async def go():
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        reader.feed_eof()
        return await read_packet(reader)
    return run(go())


def test_protocol_roundtrip_and_validation():
    assert parse(encode_packet(PCM_8K, PCM)) == (PCM_8K, PCM)
    assert parse(encode_packet(UUID_PACKET, UID)) == (UUID_PACKET, UID)
    with pytest.raises(ProtocolError):
        parse(encode_packet(UUID_PACKET, b"x"))
    with pytest.raises(ProtocolError):
        parse(encode_packet(PCM_8K, b"x"))
    with pytest.raises(ProtocolError):
        parse(encode_packet(HANGUP, b"x"))
    with pytest.raises(asyncio.IncompleteReadError):
        parse(b"\x10\x00\x02\x00")


async def start(handler=None, **kw):
    srv = AudioSocketServer(ServerSettings(audiosocket_port=0, **kw), handler=handler, pace_s=0)
    await srv.start()
    return srv


async def until(pred, timeout=2.0):
    end = asyncio.get_running_loop().time() + timeout
    while not pred():
        assert asyncio.get_running_loop().time() < end, "condition not reached"
        await asyncio.sleep(0.01)


def test_default_handler_counts_and_echoes():
    async def go():
        srv = await start(echo_audio=True)
        total = []
        orig = srv.hooks.on_audio_chunk

        async def spy(session, pcm):
            await orig(session, pcm)
            total.append(session.received_bytes)
        srv.hooks.on_audio_chunk = spy
        r, w = await asyncio.open_connection("127.0.0.1", srv.port)
        w.write(encode_packet(UUID_PACKET, UID))
        for _ in range(3):
            w.write(encode_packet(PCM_8K, PCM))
        w.write(encode_packet(DTMF, b"1"))
        w.write(encode_packet(HANGUP))
        await w.drain()
        echoed = [await asyncio.wait_for(read_packet(r), 2) for _ in range(3)]
        await until(lambda: not srv.sessions)
        w.close()
        await srv.stop()
        return echoed, total
    echoed, total = run(go())
    assert echoed == [(PCM_8K, PCM)] * 3 and total == [320, 640, 960]


def test_capacity_limit_rejects_second_call():
    async def go():
        srv = await start(max_calls=1)
        r1, w1 = await asyncio.open_connection("127.0.0.1", srv.port)
        w1.write(encode_packet(UUID_PACKET, UID))
        await w1.drain()
        await until(lambda: len(srv.sessions) == 1)
        r2, w2 = await asyncio.open_connection("127.0.0.1", srv.port)
        rejected = await asyncio.wait_for(read_packet(r2), 2)
        w1.write(encode_packet(HANGUP))
        await w1.drain()
        await until(lambda: not srv.sessions)
        for w in (w1, w2):
            w.close()
        await srv.stop()
        return rejected
    assert run(go()) == (HANGUP, b"")


def test_first_frame_must_be_uuid():
    async def go():
        srv = await start()
        r, w = await asyncio.open_connection("127.0.0.1", srv.port)
        w.write(encode_packet(PCM_8K, PCM))
        await w.drain()
        data = await asyncio.wait_for(r.read(), 2)
        await until(lambda: not srv.connections)
        w.close()
        await srv.stop()
        return data, srv.sessions
    data, sessions = run(go())
    assert data == b"" and not sessions


def test_handler_exception_does_not_kill_server():
    calls = []

    async def handler(call_id, conn):
        calls.append(call_id)
        if len(calls) == 1:
            raise RuntimeError("boom")
        async for _ in conn.audio():
            pass

    async def go():
        srv = await start(handler=handler)
        for uid in (UID, bytes(reversed(UID))):
            r, w = await asyncio.open_connection("127.0.0.1", srv.port)
            w.write(encode_packet(UUID_PACKET, uid))
            w.write(encode_packet(HANGUP))
            await w.drain()
            await asyncio.wait_for(r.read(), 2)
            w.close()
            await until(lambda: not srv.connections)
        await srv.stop()
    run(go())
    assert len(calls) == 2


def test_call_timeout_closes_connection():
    async def handler(call_id, conn):
        await asyncio.sleep(30)

    async def go():
        srv = await start(handler=handler, call_timeout_sec=1)
        r, w = await asyncio.open_connection("127.0.0.1", srv.port)
        w.write(encode_packet(UUID_PACKET, UID))
        await w.drain()
        data = await asyncio.wait_for(r.read(), 4)
        w.close()
        await srv.stop()
        return data
    assert run(go()) == b""


def test_connection_play_is_chunked_and_stops_after_hangup():
    async def go():
        sent = []

        class W:
            def write(self, d):
                sent.append(d)

            async def drain(self):
                return None
        conn = Connection(asyncio.StreamReader(), W(), pace_s=0)
        await conn.play(b"\x00\x01" * 400)  # 800 bytes -> 320 + 320 + 160
        before = len(sent)
        await conn.hangup()
        await conn.play(b"\x00\x01" * 400)
        return before, sent
    before, sent = run(go())
    assert before == 3 and sent[0] == encode_packet(PCM_8K, b"\x00\x01" * 160)
    assert sent[3] == encode_packet(HANGUP) and len(sent) == 4
