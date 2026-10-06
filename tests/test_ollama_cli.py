import asyncio
import json
import httpx
import pytest
from gateway.cli import amain, load_env
from gateway.dialog.actions import parse_action
from gateway.dialog.machine import Context
from gateway.llm_ollama import OllamaLlm
from gateway.models import DialogState as S
from gateway.tools.http import ToolError


def llm_with(handler):
    return OllamaLlm("http://ollama.local", "qwen2.5:7b",
                     client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def chat_ok(content):
    return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})


GOOD = json.dumps({"intent": "price_stock", "fields": {"sku": "X-1"}, "next_action": "ask_user",
                   "reply": "Проверяю."}, ensure_ascii=False)


def test_payload_is_structured_and_private():
    seen = {}

    def h(req):
        seen.update(json.loads(req.content), path=req.url.path)
        return chat_ok(GOOD)
    ctx = Context(intent="price_stock", fields={"phone": "+375291112233", "sku": "A1"})
    raw = asyncio.run(llm_with(h).decide(S.COLLECT_FIELDS, ctx, "артикул X один"))
    assert seen["path"] == "/api/chat" and seen["stream"] is False and seen["options"] == {"temperature": 0}
    assert "call_tool" not in seen["format"]["properties"]["next_action"]["enum"]
    assert "order_status" in seen["format"]["properties"]["intent"]["enum"]
    text = json.dumps(seen["messages"], ensure_ascii=False)
    assert "артикул X один" in text and "375291112233" not in text and "price_stock" in text
    assert parse_action(raw, S.COLLECT_FIELDS).fields == {"sku": "X-1"}


def test_think_flag_only_when_set():
    seen = []

    def h(req):
        seen.append(json.loads(req.content))
        return chat_ok(GOOD)
    asyncio.run(llm_with(h).decide(S.UNDERSTAND_INTENT, Context(), "привет"))
    assert "think" not in seen[0]
    llm = OllamaLlm("http://o", "m", think=False, client=httpx.AsyncClient(transport=httpx.MockTransport(h)))
    asyncio.run(llm.decide(S.UNDERSTAND_INTENT, Context(), "привет"))
    assert seen[1]["think"] is False


def test_server_error_and_empty_content_raise():
    with pytest.raises(ToolError):
        asyncio.run(llm_with(lambda r: httpx.Response(500)).decide(S.UNDERSTAND_INTENT, Context(), "x"))
    with pytest.raises(ToolError):
        asyncio.run(llm_with(lambda r: chat_ok("  ")).decide(S.UNDERSTAND_INTENT, Context(), "x"))


def test_check_model_presence():
    ok = llm_with(lambda r: httpx.Response(200, json={"models": [{"name": "qwen2.5:7b"}]}))
    asyncio.run(ok.check())
    missing = llm_with(lambda r: httpx.Response(200, json={"models": [{"name": "other:1b"}]}))
    with pytest.raises(ToolError) as ei:
        asyncio.run(missing.check())
    assert "ollama pull qwen2.5:7b" in str(ei.value)


class Scripted:
    def __init__(self, *a):
        self.a = list(a)

    async def decide(self, state, ctx, text):
        return self.a.pop(0)


def lines(*items):
    it = iter(items)

    async def read():
        try:
            return next(it)
        except StopIteration:
            raise EOFError
    return read


def test_cli_full_demo_call():
    out = []
    o = asyncio.run(amain({}, lines("цена X-1", "да"), out.append, llm=Scripted(GOOD)))
    assert o.state is S.FINISH
    joined = "\n".join(out)
    assert "ДЕМО-данные" in joined and "Товар в наличии. Количество: 5. Цена: 199.90 BYN." in joined
    assert "[CRM-демо] исход=resolved" in joined


def test_cli_eof_hangs_up_and_empty_line_is_silence():
    out = []
    o = asyncio.run(amain({}, lines("", ""), out.append, llm=Scripted()))
    assert o.state is S.FINISH
    assert any("Не расслышал" in line for line in out)


def test_cli_reports_ollama_down():
    out = []
    import gateway.cli as cli
    orig = cli.OllamaLlm

    class Down(orig):
        def __init__(self, *a, **k):
            super().__init__(*a, client=httpx.AsyncClient(transport=httpx.MockTransport(
                lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused")))), **k)
    cli.OllamaLlm = Down
    try:
        assert asyncio.run(amain({}, lines(), out.append)) is None
    finally:
        cli.OllamaLlm = orig
    assert "Ollama недоступна" in out[0]


def test_load_env(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text('# c\nOLLAMA_MODEL="m1"\nONEC_URL=\nOTHER=1\n', encoding="utf-8")
    monkeypatch.setenv("ONEC_URL", "http://x")
    env = load_env(str(f))
    assert env["OLLAMA_MODEL"] == "m1" and env["ONEC_URL"] == "http://x"
