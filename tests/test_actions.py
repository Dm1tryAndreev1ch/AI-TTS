import json
import pytest
from gateway.dialog.actions import ActionError, parse_action
from gateway.models import DialogState as S


def raw(**kw):
    base = {"intent": "price_stock", "fields": {}, "next_action": "ask_user", "reply": "Назовите артикул."}
    base.update(kw)
    return json.dumps(base, ensure_ascii=False)


def test_valid_ask():
    assert parse_action(raw(), S.COLLECT_FIELDS).next_action == "ask_user"


def test_allowed_tool():
    a = parse_action(raw(next_action="call_tool", tool_name="get_stock_or_price", tool_args={"sku": "X"}), S.CALL_TOOL)
    assert a.tool_name == "get_stock_or_price"


def test_tool_not_allowed_in_state():
    with pytest.raises(ActionError):
        parse_action(raw(next_action="call_tool", tool_name="get_stock_or_price"), S.COLLECT_FIELDS)


def test_unknown_tool_rejected():
    with pytest.raises(ActionError):
        parse_action(raw(next_action="call_tool", tool_name="drop_database"), S.CALL_TOOL)


def test_tool_fields_without_call_tool_rejected():
    with pytest.raises(ActionError):
        parse_action(raw(tool_name="get_order_status"), S.CALL_TOOL)


def test_long_reply_rejected():
    with pytest.raises(ActionError):
        parse_action(raw(reply="Раз. Два. Три."), S.COLLECT_FIELDS)


def test_extra_keys_rejected():
    with pytest.raises(ActionError):
        parse_action(raw(secret="x"), S.COLLECT_FIELDS)


def test_not_json():
    with pytest.raises(ActionError):
        parse_action("sure! here you go", S.COLLECT_FIELDS)


def test_bad_next_action():
    with pytest.raises(ActionError):
        parse_action(raw(next_action="rm_rf"), S.COLLECT_FIELDS)
