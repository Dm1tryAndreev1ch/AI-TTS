from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import httpx
from gateway.cli import ConsoleSink, _demo_1c
from gateway.crm_sink import BitrixCrmSink
from gateway.orchestrator import CrmSink
from gateway.tools.bitrix24 import Bitrix24Client
from gateway.tools.onec import OneCClient
from gateway.tools.registry import Handler, build_registry


@dataclass
class Backends:
    tools: dict[str, Handler]
    sink: CrmSink
    closers: list[Callable[[], Awaitable[None]]] = field(default_factory=list)

    async def aclose(self) -> None:
        for close in self.closers:
            await close()


def build_backends(env: dict[str, str], out: Callable[[str], None] = print) -> Backends:
    """1C and CRM from env; without credentials, built-in DEMO data and a console CRM are used."""
    if env.get("ONEC_URL"):
        onec = OneCClient(env["ONEC_URL"], env.get("ONEC_TOKEN", ""))
        out("1С: реальный сервис")
    else:
        onec = OneCClient("http://demo.local", "demo",
                          client=httpx.AsyncClient(transport=httpx.MockTransport(_demo_1c)))
        out("1С: ДЕМО-данные (выдуманные)")
    closers = [onec.aclose]
    if env.get("BITRIX_WEBHOOK"):
        bitrix = Bitrix24Client(env["BITRIX_WEBHOOK"])
        sink: CrmSink = BitrixCrmSink(bitrix)
        closers.append(bitrix.aclose)
        out("CRM: реальный Bitrix24")
    else:
        sink = ConsoleSink(out)
        out("CRM: демо (только вывод в консоль)")
    return Backends(build_registry(onec), sink, closers)
