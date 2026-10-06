import asyncio
import json
import httpx
from gateway.crm_sink import BitrixCrmSink
from gateway.models import DialogState as S
from gateway.orchestrator import CallOrchestrator
from gateway.tools.bitrix24 import Bitrix24Client
from gateway.tools.onec import OneCClient
from gateway.tools.registry import build_registry


async def nosleep(_):
    return None


class FakeLlm:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), 0

    async def decide(self, state, ctx, user_text):
        self.calls += 1
        return self.answers.pop(0)


class FakeSpeaker:
    def __init__(self):
        self.said = []

    async def say(self, text):
        self.said.append(text)


class FakeSink:
    def __init__(self, fail=False):
        self.fail, self.saved = fail, []

    async def save_call(self, call_id, ctx, transcript, duration_sec, outcome):
        if self.fail:
            raise RuntimeError("crm down")
        self.saved.append((call_id, outcome, dict(ctx.fields)))


def act(intent, fields=None, next_action="ask_user", **kw):
    return json.dumps({"intent": intent, "fields": fields or {}, "next_action": next_action,
                       "reply": "ok", **kw}, ensure_ascii=False)


def onec(handler, retries=0):
    c = OneCClient("https://1c.local/api", "t", retries=retries, sleep=nosleep,
                   client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return build_registry(c)


STOCK_OK = lambda r: httpx.Response(200, json={"in_stock": True, "quantity": 5, "price": "199.90", "currency": "BYN"})


def make(llm, tools=None, sink=None, phone="+375291112233"):
    sp = FakeSpeaker()
    sink = sink or FakeSink()
    return CallOrchestrator("call-1", llm, sp, tools or onec(STOCK_OK), sink, caller_phone=phone), sp, sink


def run(coro):
    return asyncio.run(coro)


def test_full_price_call():
    async def go():
        o, sp, sink = make(FakeLlm(act("price_stock", {"sku": "X-1"})))
        await o.start()
        assert o.state is S.UNDERSTAND_INTENT
        await o.handle_user_text("Сколько стоит X-1?")
        assert o.state is S.CONFIRM
        await o.handle_user_text("да")
        return o, sp, sink
    o, sp, sink = run(go())
    assert o.state is S.FINISH
    assert "Товар в наличии. Количество: 5. Цена: 199.90 BYN." in sp.said
    assert sp.said[-1].startswith("Спасибо")
    assert sink.saved == [("call-1", "resolved", {"phone": "+375291112233", "sku": "X-1"})]


def test_missing_field_then_collect():
    async def go():
        llm = FakeLlm(act("price_stock"), act("price_stock", {"sku": "A-7"}))
        o, sp, _ = make(llm)
        await o.start()
        await o.handle_user_text("хочу узнать цену")
        assert o.state is S.COLLECT_FIELDS and sp.said[-1] == "Назовите артикул товара."
        await o.handle_user_text("А семь")
        return o, sp
    o, sp = run(go())
    assert o.state is S.CONFIRM and "артикул: A-7" in sp.said[-1]


def test_no_caller_id_asks_phone():
    async def go():
        o, sp, _ = make(FakeLlm(), phone=None)
        await o.start()
        assert o.state is S.IDENTIFY
        await o.handle_user_text("плюс триста семьдесят пять")
        assert o.state is S.IDENTIFY and sp.said[-1].startswith("Не расслышал.")
        await o.handle_user_text("375 29 111 22 33")
        return o
    o = run(go())
    assert o.state is S.UNDERSTAND_INTENT and o.ctx.fields["phone"] == "+375291112233"


def test_operator_request_skips_llm_and_saves_handoff():
    async def go():
        llm = FakeLlm()
        o, sp, sink = make(llm)
        await o.start()
        await o.handle_user_text("соедините с оператором")
        return o, sp, sink, llm
    o, sp, sink, llm = run(go())
    assert o.state is S.HANDOFF and llm.calls == 0
    assert sp.said[-1].startswith("Соединяю")
    assert sink.saved[0][1] == "handoff"


def test_garbage_llm_output_ends_in_handoff():
    async def go():
        o, sp, _ = make(FakeLlm("nonsense", "{bad", "still bad"))
        await o.start()
        for _ in range(3):
            await o.handle_user_text("эээ")
        return o
    assert run(go()).state is S.HANDOFF


def test_model_cannot_choose_tool():
    async def go():
        o, _, _ = make(FakeLlm(act("price_stock", next_action="call_tool", tool_name="get_stock_or_price")))
        await o.start()
        await o.handle_user_text("цена")
        return o
    o = run(go())
    assert o.state is S.UNDERSTAND_INTENT and o.ctx.retries == 1


def test_tool_down_leads_to_handoff():
    n = {"i": 0}

    def down(r):
        n["i"] += 1
        return httpx.Response(503)

    async def go():
        o, sp, _ = make(FakeLlm(act("price_stock", {"sku": "X"})), tools=onec(down))
        await o.start()
        await o.handle_user_text("цена X")
        await o.handle_user_text("да")
        return o, sp
    o, sp = run(go())
    assert o.state is S.HANDOFF and n["i"] == 3 and sp.said[-1].startswith("Соединяю")


def test_crm_failure_goes_failsafe():
    async def go():
        o, sp, _ = make(FakeLlm(act("price_stock", {"sku": "X"})), sink=FakeSink(fail=True))
        await o.start()
        await o.handle_user_text("цена")
        await o.handle_user_text("да")
        return o, sp
    o, sp = run(go())
    assert o.state is S.FAILSAFE and sp.said[-1].startswith("Извините")


def test_denied_confirmation_recollects():
    async def go():
        o, sp, _ = make(FakeLlm(act("price_stock", {"sku": "X"})))
        await o.start()
        await o.handle_user_text("цена")
        await o.handle_user_text("нет")
        return o
    assert run(go()).state is S.COLLECT_FIELDS


def test_hangup_mid_call_is_silent_finish():
    async def go():
        o, sp, _ = make(FakeLlm())
        await o.start()
        n = len(sp.said)
        await o.hangup()
        return o, sp, n
    o, sp, n = run(go())
    assert o.state is S.FINISH and len(sp.said) == n


def test_silence_exhausts_to_handoff():
    async def go():
        o, _, _ = make(FakeLlm())
        await o.start()
        for _ in range(3):
            await o.on_silence()
        return o
    assert run(go()).state is S.HANDOFF


def test_llm_exception_is_unclear_not_crash():
    class Broken:
        async def decide(self, *a):
            raise ConnectionError("ollama down")

    async def go():
        o, _, _ = make(Broken())
        await o.start()
        await o.handle_user_text("привет")
        return o
    o = run(go())
    assert o.state is S.UNDERSTAND_INTENT and o.ctx.retries == 1


def test_bitrix_sink_creates_contact_deal_and_comment():
    paths = []

    def h(req):
        paths.append(req.url.path.rsplit("/", 1)[1])
        if paths[-1] == "crm.contact.list.json":
            return httpx.Response(200, json={"result": []})
        return httpx.Response(200, json={"result": 11})
    bx = Bitrix24Client("https://x.bitrix24.ru/rest/1/tok/", sleep=nosleep,
                        client=httpx.AsyncClient(transport=httpx.MockTransport(h)))

    async def go():
        o = CallOrchestrator("c9", FakeLlm(act("price_stock", {"sku": "X"})), FakeSpeaker(),
                             onec(STOCK_OK), BitrixCrmSink(bx), caller_phone="+375291112233")
        await o.start()
        await o.handle_user_text("цена")
        await o.handle_user_text("да")
        return o
    o = run(go())
    assert o.state is S.FINISH
    assert paths == ["crm.contact.list.json", "crm.contact.add.json", "crm.deal.add.json", "crm.timeline.comment.add.json"]
