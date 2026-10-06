import numpy as np


class SileroVad:
    """Speech probability for one 512-sample 16 kHz frame (Silero VAD, runs on CPU)."""

    def __init__(self, sample_rate: int = 16000) -> None:
        import torch
        from silero_vad import load_silero_vad
        torch.set_num_threads(1)
        self._torch = torch
        self._model = load_silero_vad()
        self._sr = sample_rate

    def __call__(self, frame: bytes) -> float:
        audio = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        with self._torch.no_grad():
            return float(self._model(self._torch.from_numpy(audio), self._sr).item())

    def reset(self) -> None:
        self._model.reset_states()
