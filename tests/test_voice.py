import asyncio
import sys
import types
import numpy as np
import pytest
from gateway.models import DialogState as S
from gateway.voice.loop import run_voice_loop
from gateway.voice.segmenter import FRAME_BYTES, SegEvent, SegmenterConfig, UtteranceSegmenter

VOICED = b"\x01\x00" * (FRAME_BYTES // 2)
QUIET = b"\x00\x00" * (FRAME_BYTES // 2)


def feed(seg, pattern):
    events = []
    for frame, prob in pattern:
        r = seg.push(frame, prob)
        if r:
            events.append(r)
    return events


def test_utterance_with_preroll_and_end_silence():
    seg = UtteranceSegmenter()
    pattern = [(QUIET, 0.0)] * 20 + [(VOICED, 0.9)] * 10 + [(QUIET, 0.0)] * 30
    events = feed(seg, pattern)
    assert len(events) == 1 and events[0][0] is SegEvent.UTTERANCE
    frames = len(events[0][1]) // FRAME_BYTES
    assert frames == 10 + 10 + 22  # preroll 320ms + speech + 700ms silence (22 frames to cross it)


def test_short_blip_is_ignored():
    seg = UtteranceSegmenter()
    assert feed(seg, [(VOICED, 0.9)] * 3 + [(QUIET, 0.0)] * 40) == []


def test_idle_silence_event_once():
    seg = UtteranceSegmenter()
    events = feed(seg, [(QUIET, 0.0)] * 260)
    assert events == [(SegEvent.SILENCE, None)]


def test_max_utterance_cut():
    seg = UtteranceSegmenter(SegmenterConfig(max_utterance_ms=640))
    events = feed(seg, [(VOICED, 0.9)] * 30)
    assert events and events[0][0] is SegEvent.UTTERANCE
    assert len(events[0][1]) // FRAME_BYTES == 20


class FakeSource:
    def __init__(self, frames):
        self.frames, self.flushes = list(frames), 0

    async def get(self):
        return self.frames.pop(0) if self.frames else None

    def flush(self):
        self.flushes += 1


class FakeVad:
    resets = 0

    def __call__(self, frame):
        return 0.9 if frame == VOICED else 0.0

    def reset(self):
        FakeVad.resets += 1


class FakeStt:
    def __init__(self, *texts):
        self.texts, self.audio = list(texts), []

    async def transcribe(self, pcm):
        self.audio.append(pcm)
        return self.texts.pop(0)


class FakeCall:
    def __init__(self):
        self.finished, self.log = False, []

    async def handle_user_text(self, t):
        self.log.append(("text", t))
        if t == "стоп":
            self.finished = True

    async def on_silence(self):
        self.log.append(("silence",))

    async def hangup(self):
        self.log.append(("hangup",))
        self.finished = True


UTT = [VOICED] * 10 + [QUIET] * 25


def test_loop_routes_text_silence_and_hangup():
    src = FakeSource(UTT + UTT + [QUIET] * 260)
    call, stt, seen = FakeCall(), FakeStt("цена", ""), []
    asyncio.run(run_voice_loop(src, FakeVad(), stt, call, on_text=seen.append))
    assert call.log == [("text", "цена"), ("silence",), ("silence",), ("hangup",)]
    assert seen == ["цена", ""] and src.flushes >= 3 and len(stt.audio) == 2


def test_loop_stops_when_call_finishes():
    src = FakeSource(UTT + UTT)
    call = FakeCall()
    asyncio.run(run_voice_loop(src, FakeVad(), FakeStt("стоп", "лишнее"), call))
    assert call.log == [("text", "стоп")]


def test_whisper_stt_glue(monkeypatch):
    seen = {}

    class Seg:
        def __init__(self, t):
            self.text = t

    class FakeModel:
        def __init__(self, size, device, compute_type):
            seen["init"] = (size, device, compute_type)

        def transcribe(self, audio, **kw):
            seen["audio"], seen["kw"] = audio, kw
            return iter([Seg(" привет "), Seg("мир")]), None
    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeModel))
    from gateway.voice.stt_whisper import WhisperStt
    pcm = np.array([0, 16384, -16384], dtype=np.int16).tobytes()
    text = asyncio.run(WhisperStt("small").transcribe(pcm))
    assert text == "привет мир" and seen["init"] == ("small", "cpu", "int8")
    assert seen["audio"].dtype == np.float32 and seen["audio"].tolist() == [0.0, 0.5, -0.5]
    assert seen["kw"]["language"] == "ru" and seen["kw"]["condition_on_previous_text"] is False


def test_silero_vad_glue(monkeypatch):
    class Out:
        def item(self):
            return 0.75

    class Model:
        def __init__(self):
            self.resets = 0

        def __call__(self, tensor, sr):
            assert sr == 16000 and tensor.dtype == np.float32
            return Out()

        def reset_states(self):
            self.resets += 1
    model = Model()

    class NoGrad:
        def __enter__(self):
            return None

        def __exit__(self, *a):
            return False
    torch = types.SimpleNamespace(set_num_threads=lambda n: None, no_grad=lambda: NoGrad(), from_numpy=lambda a: a)
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "silero_vad", types.SimpleNamespace(load_silero_vad=lambda: model))
    from gateway.voice.vad_silero import SileroVad
    vad = SileroVad()
    assert vad(VOICED) == 0.75
    vad.reset()
    assert model.resets == 1


def test_piper_speaker_synth_play_and_cache(monkeypatch, tmp_path):
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
            wav_file.writeframes(b"\x00\x00" * 10)
    monkeypatch.setitem(sys.modules, "piper", types.SimpleNamespace(PiperVoice=Voice))
    model = tmp_path / "v.onnx"
    model.write_bytes(b"x")
    from gateway.voice.tts_piper import PiperSpeaker
    sp = PiperSpeaker(str(model), player=(sys.executable, "-c", "pass"))

    async def go():
        await sp.say("привет")
        await sp.say("привет")
        await sp.say("другое")
    asyncio.run(go())
    assert calls == ["привет", "другое"]
    sp.close()
    with pytest.raises(FileNotFoundError):
        PiperSpeaker(str(tmp_path / "missing.onnx"))


def test_voice_cli_full_call_with_fakes():
    from gateway.voice_cli import amain_voice
    import json

    GOOD = json.dumps({"intent": "price_stock", "fields": {"sku": "X-1"}, "next_action": "ask_user",
                       "reply": "Проверяю."}, ensure_ascii=False)

    class Llm:
        async def decide(self, state, ctx, text):
            return GOOD

    class Speaker:
        def __init__(self):
            self.said = []

        async def say(self, text):
            self.said.append(text)
    sp, out = Speaker(), []
    src = FakeSource(UTT + UTT)
    src.started = src.stopped = False
    src.start = lambda: setattr(src, "started", True)
    src.stop = lambda: setattr(src, "stopped", True)
    o = asyncio.run(amain_voice({}, out.append, llm=Llm(), vad=FakeVad(), stt=FakeStt("цена X-1", "да"),
                                speaker=sp, source=src))
    assert o.state is S.FINISH and src.started and src.stopped
    assert "Товар в наличии. Количество: 5. Цена: 199.90 BYN." in sp.said
    assert any(line == "Вы> цена X-1" for line in out)


def test_voice_cli_reports_missing_components(monkeypatch):
    from gateway.voice_cli import amain_voice

    class Llm:
        async def decide(self, *a):
            return "{}"
    monkeypatch.setitem(sys.modules, "gateway.voice.vad_silero", None)  # forces ImportError
    out = []
    assert asyncio.run(amain_voice({}, out.append, llm=Llm())) is None
    assert "Голосовые компоненты недоступны" in "\n".join(out)


def test_mic_queue_drops_oldest_and_flushes():
    from gateway.voice.mic import MicSource

    async def go():
        mic = MicSource(asyncio.get_running_loop(), max_frames=3)
        for i in range(5):
            mic._put(bytes([i]))
        got = [await mic.get() for _ in range(3)]
        mic._put(b"x")
        mic.flush()
        return got, mic._q.empty()
    got, empty = asyncio.run(go())
    assert got == [b"\x02", b"\x03", b"\x04"] and empty
