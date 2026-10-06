import asyncio
import json
import httpx
import pytest
from gateway.tools.bitrix24 import Bitrix24Client
from gateway.tools.http import ToolError
from gateway.tools.onec import OneCClient
from gateway.tools.registry import build_registry, run_tool

HOOK = "https://example.bitrix24.ru/rest/1/SECRETTOKEN/"


async def nosleep(_: float) -> None:
    return None


def bx(handler):
    return Bitrix24Client(HOOK, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), sleep=nosleep)


def oc(handler, retries=1):
    return OneCClient("https://1c.local/api", "tok", retries=retries, sleep=nosleep,
                      client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_find_contact_found_and_empty():
    def h(req):
        assert req.url.path.endswith("/crm.contact.list.json")
        body = json.loads(req.content)
        assert body["filter"] == {"PHONE": "+375291112233"}
        return httpx.Response(200, json={"result": [{"ID": "7", "NAME": "Ivan"}]})
    c = asyncio.run(bx(h).find_contact_by_phone("+375 29 111-22-33"))
    assert (c.id, c.name) == (7, "Ivan")
    empty = bx(lambda r: httpx.Response(200, json={"result": []}))
    assert asyncio.run(empty.find_contact_by_phone("+375291112233")) is None


def test_invalid_phone_rejected_before_request():
    def h(req):
        raise AssertionError("no request expected")
    with pytest.raises(ToolError):
        asyncio.run(bx(h).find_contact_by_phone("abc"))


def test_create_deal_idempotent_and_uses_contact_ids():
    calls = []

    def h(req):
        calls.append(json.loads(req.content))
        return httpx.Response(200, json={"result": 55})
    client = bx(h)

    async def go():
        a = await client.create_deal(7, "Звонок", "итог", "voice", idempotency_key="call-1")
        b = await client.create_deal(7, "Звонок", "итог", "voice", idempotency_key="call-1")
        return a, b
    assert asyncio.run(go()) == (55, 55)
    assert len(calls) == 1 and calls[0]["fields"]["CONTACT_IDS"] == [7]


def test_retry_on_5xx_then_success():
    n = {"i": 0}

    def h(req):
        n["i"] += 1
        return httpx.Response(502) if n["i"] < 3 else httpx.Response(200, json={"result": 9})
    assert asyncio.run(bx(h).create_deal(1, "t", "s", "x")) == 9
    assert n["i"] == 3


def test_error_never_leaks_webhook_secret():
    def h(req):
        return httpx.Response(500, text="boom " + HOOK)
    with pytest.raises(ToolError) as ei:
        asyncio.run(bx(h).create_deal(1, "t", "s", "x"))
    assert "SECRETTOKEN" not in str(ei.value) and "example.bitrix24" not in str(ei.value)


def test_api_error_payload_is_tool_error():
    c = bx(lambda r: httpx.Response(200, json={"error": "ACCESS_DENIED", "error_description": HOOK}))
    with pytest.raises(ToolError) as ei:
        asyncio.run(c.create_deal(1, "t", "s", "x"))
    assert "SECRETTOKEN" not in str(ei.value)


def test_update_contact_field_allowlist():
    c = bx(lambda r: httpx.Response(200, json={"result": True}))
    assert asyncio.run(c.update_contact(1, {"NAME": "A"})) is True
    with pytest.raises(ToolError):
        asyncio.run(c.update_contact(1, {"ASSIGNED_BY_ID": 1}))


def test_add_activity_uses_timeline_comment():
    seen = {}

    def h(req):
        seen["path"] = req.url.path
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"result": 3})
    assert asyncio.run(bx(h).add_activity(55, "итог", "текст", 42)) == 3
    assert seen["path"].endswith("/crm.timeline.comment.add.json")
    assert seen["body"]["fields"]["ENTITY_TYPE"] == "deal"


def test_onec_order_status_ok_and_auth_header():
    def h(req):
        assert req.headers["authorization"] == "Bearer tok"
        assert req.url.params["order"] == "A-1" and req.url.params["phone_last4"] == "1234"
        return httpx.Response(200, json={"status": "Отгружен", "eta": "10.10", "internal": "x"})
    r = asyncio.run(oc(h).get_order_status("A-1", "1234"))
    assert r.speakable() == "Статус заказа: Отгружен. Ожидаемая дата: 10.10."


@pytest.mark.parametrize("order,last4", [("A 1; DROP", "1234"), ("A-1", "12"), ("", "1234"), ("A-1", "12ab")])
def test_onec_rejects_bad_input(order, last4):
    def h(req):
        raise AssertionError("no request expected")
    with pytest.raises(ToolError):
        asyncio.run(oc(h).get_order_status(order, last4))


def test_onec_stock_price_speech():
    c = oc(lambda r: httpx.Response(200, json={"in_stock": True, "quantity": 5, "price": "199.90", "currency": "BYN"}))
    assert asyncio.run(c.get_stock_or_price("X-1")).speakable() == "Товар в наличии. Количество: 5. Цена: 199.90 BYN."


def test_onec_4xx_not_retried_5xx_retried():
    n = {"i": 0}

    def h4(req):
        n["i"] += 1
        return httpx.Response(404)
    with pytest.raises(ToolError):
        asyncio.run(oc(h4, retries=3).get_stock_or_price("X"))
    assert n["i"] == 1
    n["i"] = 0

    def h5(req):
        n["i"] += 1
        return httpx.Response(503)
    with pytest.raises(ToolError) as ei:
        asyncio.run(oc(h5, retries=2).get_stock_or_price("X"))
    assert n["i"] == 3 and ei.value.retryable


def test_onec_malformed_response():
    c = oc(lambda r: httpx.Response(200, json={"unexpected": 1}))
    with pytest.raises(ToolError):
        asyncio.run(c.get_stock_or_price("X"))


def test_registry_blocks_unknown_and_wraps_errors():
    reg = build_registry(oc(lambda r: httpx.Response(503), retries=0))

    async def go():
        return (await run_tool(reg, "drop_database", {}),
                await run_tool(reg, "get_stock_or_price", {"sku": "X"}),
                await run_tool(reg, "get_stock_or_price", {"sku": "bad sku!"}))
    unknown, down, rejected = asyncio.run(go())
    assert unknown.error == "unknown_tool"
    assert down.error == "tool_unavailable" and not down.ok
    assert rejected.error == "tool_rejected"
