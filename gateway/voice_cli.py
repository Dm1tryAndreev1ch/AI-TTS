"""Voice demo on a laptop: mic -> Silero VAD -> faster-whisper -> orchestrator -> Piper -> speakers."""
import asyncio
import os
import sys
import uuid
from collections.abc import Callable
import httpx
from gateway.cli import ConsoleSink, _demo_1c, load_env
from gateway.crm_sink import BitrixCrmSink
from gateway.llm_ollama import OllamaLlm
from gateway.orchestrator import CallOrchestrator, Llm, Speaker
from gateway.tools.bitrix24 import Bitrix24Client
from gateway.tools.http import ToolError
from gateway.tools.onec import OneCClient
from gateway.tools.registry import build_registry
from gateway.voice.loop import FrameSource, Stt, Vad, run_voice_loop

VOICE_PREFIXES = ("WHISPER_", "PIPER_", "VOICE_")


async def amain_voice(env: dict[str, str], out: Callable[[str], None] = print, *, llm: Llm | None = None,
                      vad: Vad | None = None, stt: Stt | None = None, speaker: Speaker | None = None,
                      source: FrameSource | None = None) -> CallOrchestrator | None:
    own_llm: OllamaLlm | None = None
    if llm is None:
        own_llm = OllamaLlm(env.get("OLLAMA_URL") or "http://127.0.0.1:11434",
                            env.get("OLLAMA_MODEL") or "qwen2.5:7b")
        try:
            await own_llm.check()
        except ToolError as exc:
            out(f"Ollama недоступна: {exc}. Запустите: brew services start ollama")
            await own_llm.aclose()
            return None
        llm = own_llm

    try:
        out("Загрузка моделей (первый запуск скачивает модель распознавания)...")
        if vad is None:
            from gateway.voice.vad_silero import SileroVad
            vad = SileroVad()
        if stt is None:
            from gateway.voice.stt_whisper import WhisperStt
            stt = WhisperStt(env.get("WHISPER_MODEL") or "small")
        if speaker is None:
            from gateway.voice.tts_piper import PiperSpeaker
            voice_path = env.get("PIPER_VOICE") or "models/ru_RU-irina-medium.onnx"
            speaker = PiperSpeaker(voice_path, (env.get("VOICE_PLAYER") or "afplay",))
        if source is None:
            from gateway.voice.mic import MicSource
            source = MicSource(asyncio.get_running_loop())
    except (ImportError, FileNotFoundError) as exc:
        out(f"Голосовые компоненты недоступны: {exc}. Установите: pip install -e '.[voice]' "
            f"и скачайте голос (scripts/setup_voice_mac.sh)")
        if own_llm:
            await own_llm.aclose()
        return None

    if env.get("ONEC_URL"):
        onec = OneCClient(env["ONEC_URL"], env.get("ONEC_TOKEN", ""))
        out("1С: реальный сервис")
    else:
        onec = OneCClient("http://demo.local", "demo",
                          client=httpx.AsyncClient(transport=httpx.MockTransport(_demo_1c)))
        out("1С: ДЕМО-данные (выдуманные)")
    if env.get("BITRIX_WEBHOOK"):
        bitrix = Bitrix24Client(env["BITRIX_WEBHOOK"])
        sink = BitrixCrmSink(bitrix)
        out("CRM: реальный Bitrix24")
    else:
        bitrix, sink = None, ConsoleSink(out)
        out("CRM: демо (только вывод в консоль)")

    orch = CallOrchestrator(str(uuid.uuid4()), llm, speaker, build_registry(onec), sink,
                            caller_phone=env.get("DEMO_CALLER_PHONE") or "+375290000000")
    out("Говорите после приветствия. Лучше в наушниках. Ctrl+C = выход.")
    start = getattr(source, "start", None)
    if start:
        start()
    try:
        await orch.start()
        await run_voice_loop(source, vad, stt, orch, on_text=lambda t: out(f"Вы> {t or '(не распознано)'}"))
        out(f"Звонок завершён: {orch.state.value}")
    finally:
        stop = getattr(source, "stop", None)
        if stop:
            stop()
        close = getattr(speaker, "close", None)
        if close:
            close()
        if own_llm:
            await own_llm.aclose()
        await onec.aclose()
        if bitrix:
            await bitrix.aclose()
    return orch


def main() -> None:
    env = load_env()
    env.update({k: v for k, v in os.environ.items() if k.startswith(VOICE_PREFIXES)})
    try:
        asyncio.run(amain_voice(env))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
