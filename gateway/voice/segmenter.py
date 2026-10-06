"""Splits a stream of 16 kHz mono PCM16 frames into utterances using per-frame speech probabilities."""
from collections import deque
from dataclasses import dataclass
from enum import Enum

SAMPLE_RATE = 16000
FRAME_SAMPLES = 512  # 32 ms, the chunk size Silero VAD expects at 16 kHz
FRAME_BYTES = FRAME_SAMPLES * 2


class SegEvent(Enum):
    UTTERANCE = "utterance"
    SILENCE = "silence"


@dataclass(frozen=True)
class SegmenterConfig:
    threshold: float = 0.5
    min_speech_ms: int = 192
    end_silence_ms: int = 700
    max_utterance_ms: int = 15000
    preroll_ms: int = 320
    idle_silence_ms: int = 8000
    frame_ms: int = 32


class UtteranceSegmenter:
    def __init__(self, config: SegmenterConfig | None = None) -> None:
        self.cfg = config or SegmenterConfig()
        self._preroll: deque[bytes] = deque(maxlen=max(1, self.cfg.preroll_ms // self.cfg.frame_ms))
        self.reset()

    def reset(self) -> None:
        self._preroll.clear()
        self._buf: list[bytes] = []
        self._in_speech = False
        self._voiced_ms = 0
        self._silence_ms = 0
        self._total_ms = 0
        self._idle_ms = 0

    def push(self, frame: bytes, prob: float) -> tuple[SegEvent, bytes | None] | None:
        c = self.cfg
        voiced = prob >= c.threshold
        if not self._in_speech:
            if not voiced:
                self._preroll.append(frame)
                self._idle_ms += c.frame_ms
                if self._idle_ms >= c.idle_silence_ms:
                    self._idle_ms = 0
                    return SegEvent.SILENCE, None
                return None
            self._in_speech = True
            self._buf = [*self._preroll, frame]
            self._preroll.clear()
            self._voiced_ms = c.frame_ms
            self._silence_ms = 0
            self._total_ms = len(self._buf) * c.frame_ms
            return None
        self._buf.append(frame)
        self._total_ms += c.frame_ms
        if voiced:
            self._voiced_ms += c.frame_ms
            self._silence_ms = 0
        else:
            self._silence_ms += c.frame_ms
        if self._silence_ms >= c.end_silence_ms or self._total_ms >= c.max_utterance_ms:
            audio = b"".join(self._buf)
            long_enough = self._voiced_ms >= c.min_speech_ms
            self._in_speech = False
            self._buf = []
            self._preroll.clear()
            if long_enough:
                self._idle_ms = 0
                return SegEvent.UTTERANCE, audio
        return None
