"""Phone mode: Asterisk AudioSocket -> VAD -> faster-whisper -> orchestrator -> Piper -> caller.
Runs one call at a time. Use a Linux host with Asterisk; the AudioSocket port has no authentication."""
import asyncio
import os
import sys
from collections.abc import Callable
from gateway.backends import build_backends
from gateway.cli import load_env
from gateway.llm_ollama import OllamaLlm
from gateway.orchestrator import CallOrchestrator, Llm
from gateway.server import AudioSocketServer, ServerSettings
from gateway.telephony.bridge import AudioSocketSpeaker, PcmTts, serve_call
from gateway.tools.http import ToolError
from gateway.voice.loop import Stt, Vad

ENV_PREFIXES = ("WHISPER_", "PIPER_", "TELEPHONY_", "AUDIOSOCKET_", "CALL_")


async def amain_telephony(env: dict[str, str], out: Callable[[str], None] = print, *, llm: Llm | None = None,
                          vad: Vad | None = None, stt: Stt | None = None, tts: PcmTts | None = None,
                          stop: asyncio.Event | None = None,
                          on_ready: Callable[[int], None] | None = None) -> None:
    own_llm: OllamaLlm | None = None
    if llm is None:
        own_llm = OllamaLlm(env.get("OLLAMA_URL") or "http://127.0.0.1:11434",
                            env.get("OLLAMA_MODEL") or "qwen2.5:7b")
        try:
            await own_llm.check()
        except ToolError as exc:
            out(f"Ollama недоступна: {exc}")
            await own_llm.aclose()
            return
        llm = own_llm
    try:
        out("Загрузка моделей...")
        if vad is None:
            from gateway.voice.vad_silero import SileroVad
            vad = SileroVad()
        if stt is None:
            from gateway.voice.stt_whisper import WhisperStt
            stt = WhisperStt(env.get("WHISPER_MODEL") or "small")
        if tts is None:
            from gateway.voice.tts_pcm import PiperPcm
            tts = PiperPcm(env.get("PIPER_VOICE") or "models/ru_RU-irina-medium.onnx")
    except (ImportError, FileNotFoundError) as exc:
        out(f"Голосовые компоненты недоступны: {exc}. Установите: pip install -e '.[voice]'")
        if own_llm:
            await own_llm.aclose()
        return

    backends = build_backends(env, out)
    caller_phone = env.get("TELEPHONY_CALLER_PHONE") or None  # AudioSocket does not carry caller ID

    def make_call(call_id: str, speaker: AudioSocketSpeaker) -> CallOrchestrator:
        return CallOrchestrator(call_id, llm, speaker, backends.tools, backends.sink, caller_phone=caller_phone)

    async def handler(call_id, conn) -> None:
        await serve_call(call_id, conn, make_call=make_call, vad=vad, stt=stt, tts=tts,
                         on_text=lambda t: out(f"Клиент> {t or '(не распознано)'}"))

    settings = ServerSettings(
        audiosocket_host=env.get("TELEPHONY_BIND") or "127.0.0.1",
        audiosocket_port=int(env.get("AUDIOSOCKET_PORT") or 9092),
        max_calls=1,  # VAD and models are shared, so only one call at a time
        call_timeout_sec=int(env.get("CALL_TIMEOUT_SEC") or 600),
    )
    server = AudioSocketServer(settings, handler=handler)
    await server.start()
    out(f"AudioSocket слушает {settings.audiosocket_host}:{server.port}")
    if on_ready:
        on_ready(server.port)
    try:
        await (stop or asyncio.Event()).wait()
    finally:
        await server.stop()
        await backends.aclose()
        if own_llm:
            await own_llm.aclose()


def main() -> None:
    env = load_env()
    env.update({k: v for k, v in os.environ.items() if k.startswith(ENV_PREFIXES)})
    try:
        asyncio.run(amain_telephony(env))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
