import pytest
from gateway.dialog.machine import Context, Event, next_state
from gateway.models import DialogState as S


def run(state, events, ctx=None):
    ctx = ctx or Context()
    for e in events:
        state = next_state(state, e, ctx)
    return state, ctx


def test_order_status_happy_path():
    ctx = Context(intent="order_status", fields={"order_number": "A1", "phone_last4": "1234"})
    s, _ = run(S.GREETING, [Event.GREETING_DONE, Event.IDENTIFIED, Event.INTENT_RECOGNIZED,
                            Event.USER_CONFIRMED, Event.TOOL_OK, Event.RESULT_REPORTED,
                            Event.CRM_SAVED], ctx)
    assert s is S.FINISH


def test_missing_fields_go_to_collect_then_confirm():
    ctx = Context(intent="price_stock")
    s, ctx = run(S.UNDERSTAND_INTENT, [Event.INTENT_RECOGNIZED], ctx)
    assert s is S.COLLECT_FIELDS
    ctx.fields["sku"] = "X-1"
    assert next_state(s, Event.FIELDS_UPDATED, ctx) is S.CONFIRM


def test_callback_skips_tool():
    ctx = Context(intent="callback", fields={"name": "Ivan", "phone": "+375291112233"})
    s, _ = run(S.CONFIRM, [Event.USER_CONFIRMED], ctx)
    assert s is S.SAVE_CRM


def test_denied_confirmation_returns_to_collect():
    assert run(S.CONFIRM, [Event.USER_DENIED])[0] is S.COLLECT_FIELDS


@pytest.mark.parametrize("state", [S.IDENTIFY, S.COLLECT_FIELDS, S.CALL_TOOL, S.CONFIRM])
def test_operator_request_always_handoff(state):
    assert run(state, [Event.OPERATOR_REQUESTED])[0] is S.HANDOFF


def test_silence_exhausts_retries_then_handoff():
    s, _ = run(S.UNDERSTAND_INTENT, [Event.SILENCE] * 3)
    assert s is S.HANDOFF


def test_retry_counter_resets_on_transition():
    ctx = Context()
    s = next_state(S.IDENTIFY, Event.UNCLEAR, ctx)
    assert (s, ctx.retries) == (S.IDENTIFY, 1)
    assert next_state(s, Event.IDENTIFIED, ctx) is S.UNDERSTAND_INTENT
    assert ctx.retries == 0


def test_tool_errors_end_in_handoff():
    ctx = Context(intent="price_stock", fields={"sku": "X"})
    assert run(S.CALL_TOOL, [Event.TOOL_ERROR] * 3, ctx)[0] is S.HANDOFF


def test_crm_failure_goes_to_failsafe():
    assert run(S.SAVE_CRM, [Event.CRM_FAILED] * 3)[0] is S.FAILSAFE


def test_terminal_states_are_sticky():
    assert run(S.FINISH, [Event.OPERATOR_REQUESTED])[0] is S.FINISH
    assert run(S.HANDOFF, [Event.HANGUP])[0] is S.HANDOFF


def test_hangup_finishes():
    assert run(S.COLLECT_FIELDS, [Event.HANGUP])[0] is S.FINISH


def test_unknown_intent_does_not_advance():
    ctx = Context(intent="weather")
    assert run(S.UNDERSTAND_INTENT, [Event.INTENT_RECOGNIZED], ctx)[0] is S.UNDERSTAND_INTENT


def test_confirm_with_missing_fields_is_failsafe():
    ctx = Context(intent="order_status", fields={"order_number": "A1"})
    assert run(S.CONFIRM, [Event.USER_CONFIRMED], ctx)[0] is S.FAILSAFE
