import asyncio
import json
import sys
import types
import numpy as np
from gateway.audiosocket import Connection
from gateway.protocol import HANGUP, PCM_8K, UUID_PACKET, encode_packet, read_packet
from gateway.server import AudioSocketServer, ServerSettings
from gateway.telephony.bridge import AudioSocketFrameSource, serve_call
from gateway.telephony.resample import resample_to_8k, upsample_8k_to_16k
from gateway.telephony_cli import amain_telephony

UID = bytes(range(16))
VOICED_8K = np.full(256, 2000, dtype=np.int16).tobytes()  # one 32 ms frame at 8 kHz
QUIET_8K = bytes(512)
TTS_PCM = np.full(800, 500, dtype=np.int16).tobytes()  # 100 ms at 8 kHz = 1600 bytes
UTT = VOICED_8K * 10 + QUIET_8K * 30


def run(coro):
    return asyncio.run(coro)


def test_resample_shapes_and_tone():
    assert len(upsample_8k_to_16k(bytes(320))) == 640
    assert upsample_8k_to_16k(b"") == b""
    t = np.arange(22050) / 22050
    tone = (np.sin(2 * np.pi * 440 * t) * 10000).astype(np.int16).tobytes()
    out = np.frombuffer(resample_to_8k(tone, 22050), dtype=np.int16)
    assert abs(len(out) - 8000) <= 2
    crossings = np.sum(np.diff(np.signbit(out).astype(int)) != 0) / 2
    assert 420 <= crossings <= 460 and np.abs(out).max() > 8000
    assert resample_to_8k(tone[:10], 8000) == tone[:10]


def test_frame_source_framing_close_and_flush():
    async def go():
        src = AudioSocketFrameSource()
        for _ in range(4):
            src.feed(b"\x01\x00" * 160)  # 4 x 320 = 1280 bytes -> 2 frames + remainder
        frames = [await src.get(), await src.get()]
        src.feed(b"\x01\x00" * 160)
        src.flush()
        src.close()
        src.flush()
        return frames, await asyncio.wait_for(src.get(), 1)
    frames, last = run(go())
    assert [len(f) for f in frames] == [1024, 1024] and last is None


class Vad16:
    def __call__(self, frame):
        return 0.9 if np.frombuffer(frame, dtype=np.int16).max() > 1000 else 0.0

    def reset(self):
        pass


class FakeStt:
    def __init__(self, *texts):
        self.texts = list(texts)

    async def transcribe(self, pcm):
        return self.texts.pop(0)


class FakeTts:
    def __init__(self):
        self.said = []

    async def synth(self, text):
        self.said.append(text)
        return TTS_PCM, 8000


class FakeCall:
    def __init__(self, speaker):
        self.speaker, self.finished = speaker, False

    async def start(self):
        await self.speaker.say("привет")

    async def handle_user_text(self, text):
        await self.speaker.say("ответ: " + text)
        self.finished = True

    async def on_silence(self):
        pass

    async def hangup(self):
        self.finished = True


async def send_audio(w, pcm):
    for i in range(0, len(pcm), 320):
        w.write(encode_packet(PCM_8K, pcm[i:i + 320]))
    await w.drain()


async def read_audio(r, nbytes=None):
    """Read packets until nbytes of audio arrived, or until HANGUP when nbytes is None."""
    total, hung = 0, False
    while nbytes is None or total < nbytes:
        kind, payload = await asyncio.wait_for(read_packet(r), 5)
        if kind == PCM_8K:
            total += len(payload)
        elif kind == HANGUP:
            hung = True
            break
    return total, hung


def test_bridge_over_real_tcp_with_fake_dialog():
    tts = FakeTts()

    async def handler(call_id, conn):
        await serve_call(call_id, conn, make_call=lambda cid, sp: FakeCall(sp), vad=Vad16(),
                         stt=FakeStt("привет мир"), tts=tts)

    async def go():
        srv = AudioSocketServer(ServerSettings(audiosocket_port=0), handler=handler, pace_s=0)
        await srv.start()
        r, w = await asyncio.open_connection("127.0.0.1", srv.port)
        w.write(encode_packet(UUID_PACKET, UID))
        await w.drain()
        greeting, _ = await read_audio(r, 1600)
        await asyncio.sleep(0.1)
        await send_audio(w, UTT)
        rest, hung = await read_audio(r)
        w.close()
        await srv.stop()
        return greeting, rest, hung
    greeting, rest, hung = run(go())
    assert greeting == 1600 and rest == 1600 and hung
    assert tts.said == ["привет", "ответ: привет мир"]


def test_caller_hangup_during_call_ends_cleanly():
    async def handler(call_id, conn):
        await serve_call(call_id, conn, make_call=lambda cid, sp: FakeCall(sp), vad=Vad16(),
                         stt=FakeStt(), tts=FakeTts())

    async def go():
        srv = AudioSocketServer(ServerSettings(audiosocket_port=0), handler=handler, pace_s=0)
        await srv.start()
        r, w = await asyncio.open_connection("127.0.0.1", srv.port)
        w.write(encode_packet(UUID_PACKET, UID))
        await w.drain()
        await read_audio(r, 1600)
        w.write(encode_packet(HANGUP))
        await w.drain()
        for _ in range(100):
            if not srv.sessions:
                break
            await asyncio.sleep(0.02)
        w.close()
        await srv.stop()
        return srv.sessions
    assert run(go()) == {}


def test_full_phone_call_with_real_orchestrator():
    GOOD = json.dumps({"intent": "price_stock", "fields": {"sku": "X-1"}, "next_action": "ask_user",
                       "reply": "Проверяю."}, ensure_ascii=False)

    class Llm:
        async def decide(self, state, ctx, text):
            return GOOD
    tts, out, port_box = FakeTts(), [], {}

    async def go():
        stop = asyncio.Event()
        ready = asyncio.get_running_loop().create_future()
        env = {"AUDIOSOCKET_PORT": "0", "TELEPHONY_CALLER_PHONE": "+375291112233"}
        task = asyncio.create_task(amain_telephony(env, out.append, llm=Llm(), vad=Vad16(),
                                                   stt=FakeStt("цена X-1", "да"), tts=tts, stop=stop,
                                                   on_ready=ready.set_result))
        port = await asyncio.wait_for(ready, 3)
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(encode_packet(UUID_PACKET, UID))
        await w.drain()
        total, _ = await read_audio(r, 3200)  # greeting + "how can I help"
        await asyncio.sleep(0.1)
        await send_audio(w, UTT)
        more, _ = await read_audio(r, 1600)  # confirmation question
        await asyncio.sleep(0.1)
        await send_audio(w, UTT)
        rest, hung = await read_audio(r)  # price, goodbye, HANGUP
        w.close()
        stop.set()
        await asyncio.wait_for(task, 3)
        return total, more, rest, hung
    total, more, rest, hung = run(go())
    assert (total, more, rest, hung) == (3200, 1600, 3200, True)
    assert "Товар в наличии. Количество: 5. Цена: 199.90 BYN." in tts.said
    joined = "\n".join(out)
    assert "Клиент> цена X-1" in joined and "[CRM-демо] исход=resolved" in joined


def test_piper_pcm_adapter(monkeypatch, tmp_path):
    import wave
    calls = []

    class Voice:
        @staticmethod
        def load(path):
            return Voice()

        def synthesize_wav(self, text, wav_file):
            calls.append(text)
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            wav_file.writeframes(b"\x01\x00" * 100)
    monkeypatch.setitem(sys.modules, "piper", types.SimpleNamespace(PiperVoice=Voice))
    model = tmp_path / "v.onnx"
    model.write_bytes(b"x")
    from gateway.voice.tts_pcm import PiperPcm
    tts = PiperPcm(str(model))
    a = run(tts.synth("привет"))
    b = run(tts.synth("привет"))
    assert a == (b"\x01\x00" * 100, 22050) and a == b and calls == ["привет"]
