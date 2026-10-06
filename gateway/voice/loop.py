from typing import Protocol
from gateway.voice.segmenter import SegEvent, UtteranceSegmenter


class FrameSource(Protocol):
    async def get(self) -> bytes | None: ...
    def flush(self) -> None: ...


class Vad(Protocol):
    def __call__(self, frame: bytes) -> float: ...
    def reset(self) -> None: ...


class Stt(Protocol):
    async def transcribe(self, pcm: bytes) -> str: ...


class CallLike(Protocol):
    finished: bool
    async def handle_user_text(self, text: str) -> None: ...
    async def on_silence(self) -> None: ...
    async def hangup(self) -> None: ...


async def run_voice_loop(source: FrameSource, vad: Vad, stt: Stt, call: CallLike,
                         segmenter: UtteranceSegmenter | None = None, on_text=None) -> None:
    """Half-duplex loop: while the agent speaks or thinks, mic frames are not consumed and are
    flushed afterwards, so the agent never hears itself (use headphones for best results)."""
    seg = segmenter or UtteranceSegmenter()
    source.flush()
    while not call.finished:
        frame = await source.get()
        if frame is None:
            await call.hangup()
            return
        result = seg.push(frame, vad(frame))
        if result is None:
            continue
        kind, audio = result
        if kind is SegEvent.UTTERANCE and audio:
            text = (await stt.transcribe(audio)).strip()
            if on_text:
                on_text(text)
            if text:
                await call.handle_user_text(text)
            else:
                await call.on_silence()
        else:
            await call.on_silence()
        source.flush()
        seg.reset()
        vad.reset()
