import numpy as np


def upsample_8k_to_16k(pcm: bytes) -> bytes:
    """Linear 2x upsampling of PCM16 mono (stateless, fine for telephone-band speech)."""
    x = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16).astype(np.int32)
    if x.size == 0:
        return b""
    nxt = np.append(x[1:], x[-1])
    out = np.empty(x.size * 2, dtype=np.int16)
    out[0::2] = x
    out[1::2] = (x + nxt) // 2
    return out.tobytes()


def resample_to_8k(pcm: bytes, src_rate: int) -> bytes:
    """Resample PCM16 mono to 8 kHz: box low-pass when downsampling, then linear interpolation."""
    if src_rate == 8000:
        return pcm[: len(pcm) // 2 * 2]
    x = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16).astype(np.float32)
    if x.size == 0:
        return b""
    k = round(src_rate / 8000)
    if k > 1:
        x = np.convolve(x, np.ones(k, dtype=np.float32) / k, mode="same")
    n_out = int(x.size * 8000 / src_rate)
    t = np.arange(n_out) * (src_rate / 8000)
    y = np.interp(t, np.arange(x.size), x)
    return np.clip(y, -32768, 32767).astype(np.int16).tobytes()
