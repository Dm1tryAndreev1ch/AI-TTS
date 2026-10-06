"""Text-mode demo: talk to the call orchestrator in the terminal (no telephony, no audio)."""
import asyncio
import os
import sys
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
import httpx
from gateway.crm_sink import BitrixCrmSink
from gateway.dialog.machine import Context
from gateway.llm_ollama import OllamaLlm
from gateway.orchestrator import CallOrchestrator, Llm
from gateway.tools.bitrix24 import Bitrix24Client
from gateway.tools.http import ToolError
from gateway.tools.onec import OneCClient
from gateway.tools.registry import build_registry

ENV_PREFIXES = ("OLLAMA_", "ONEC_", "BITRIX_", "DEMO_")


def load_env(path: str = ".env") -> dict[str, str]:
    env: dict[str, str] = {}
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k.startswith(ENV_PREFIXES)})
    return env


def _demo_1c(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/stock/price"):
        return httpx.Response(200, json={"in_stock": True, "quantity": 5, "price": "199.90", "currency": "BYN"})
    if request.url.path.endswith("/orders/status"):
        return httpx.Response(200, json={"status": "передан в доставку", "eta": "завтра"})
    return httpx.Response(404)


class ConsoleSpeaker:
    def __init__(self, out: Callable[[str], None]) -> None:
        self._out = out

    async def say(self, text: str) -> None:
        self._out(f"Агент> {text}")


class ConsoleSink:
    def __init__(self, out: Callable[[str], None]) -> None:
        self._out = out

    async def save_call(self, call_id: str, ctx: Context, transcript: list[tuple[str, str]],
                        duration_sec: int, outcome: str) -> None:
        self._out(f"[CRM-демо] исход={outcome} намерение={ctx.intent} "
                  f"поля={ {k: v for k, v in ctx.fields.items() if k != 'phone'} } длительность={duration_sec}с")


async def _stdin_line() -> str:
    return await asyncio.to_thread(input, "Вы> ")


async def amain(env: dict[str, str], read_line: Callable[[], Awaitable[str]] = _stdin_line,
                out: Callable[[str], None] = print, llm: Llm | None = None) -> CallOrchestrator | None:
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

    if env.get("ONEC_URL"):
        onec = OneCClient(env["ONEC_URL"], env.get("ONEC_TOKEN", ""))
        out("1С: реальный сервис")
    else:
        onec = OneCClient("http://demo.local", "demo",
                          client=httpx.AsyncClient(transport=httpx.MockTransport(_demo_1c)))
        out("1С: ДЕМО-данные (выдуманные), задайте ONEC_URL для реального сервиса")
    if env.get("BITRIX_WEBHOOK"):
        bitrix = Bitrix24Client(env["BITRIX_WEBHOOK"])
        sink = BitrixCrmSink(bitrix)
        out("CRM: реальный Bitrix24")
    else:
        bitrix, sink = None, ConsoleSink(out)
        out("CRM: демо (только вывод в консоль)")

    caller = env.get("DEMO_CALLER_PHONE") or "+375290000000"
    orch = CallOrchestrator(str(uuid.uuid4()), llm, ConsoleSpeaker(out), build_registry(onec), sink,
                            caller_phone=caller)
    out("Команды: пустая строка = молчание, /hangup = положить трубку, Ctrl+D = выход")
    try:
        await orch.start()
        while not orch.finished:
            try:
                line = (await read_line()).strip()
            except EOFError:
                await orch.hangup()
                break
            if line == "/hangup":
                await orch.hangup()
            elif not line:
                await orch.on_silence()
            else:
                await orch.handle_user_text(line)
        out(f"Звонок завершён: {orch.state.value}")
    finally:
        if own_llm:
            await own_llm.aclose()
        await onec.aclose()
        if bitrix:
            await bitrix.aclose()
    return orch


def main() -> None:
    try:
        asyncio.run(amain(load_env()))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
