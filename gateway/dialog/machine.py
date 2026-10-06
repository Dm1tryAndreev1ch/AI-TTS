from dataclasses import dataclass, field
from enum import StrEnum
from gateway.dialog.specs import INTENTS, SPECS, TERMINAL
from gateway.models import DialogState as S


class Event(StrEnum):
    GREETING_DONE = "GREETING_DONE"
    IDENTIFIED = "IDENTIFIED"
    INTENT_RECOGNIZED = "INTENT_RECOGNIZED"
    FIELDS_UPDATED = "FIELDS_UPDATED"
    USER_CONFIRMED = "USER_CONFIRMED"
    USER_DENIED = "USER_DENIED"
    TOOL_OK = "TOOL_OK"
    TOOL_ERROR = "TOOL_ERROR"
    RESULT_REPORTED = "RESULT_REPORTED"
    CRM_SAVED = "CRM_SAVED"
    CRM_FAILED = "CRM_FAILED"
    OPERATOR_REQUESTED = "OPERATOR_REQUESTED"
    UNCLEAR = "UNCLEAR"
    SILENCE = "SILENCE"
    HANGUP = "HANGUP"


@dataclass
class Context:
    intent: str | None = None
    fields: dict[str, str] = field(default_factory=dict)
    retries: int = 0  # failed attempts in the current state

    def missing_fields(self) -> list[str]:
        spec = INTENTS.get(self.intent or "")
        if spec is None:
            return []
        return [f for f in spec.required_fields if not self.fields.get(f)]


def _retry(state: S, ctx: Context) -> S:
    ctx.retries += 1
    return S.HANDOFF if ctx.retries > SPECS[state].max_retries else state


def _route(state: S, event: Event, ctx: Context) -> S:
    if event in (Event.UNCLEAR, Event.SILENCE):
        return _retry(state, ctx)
    if state is S.GREETING and event is Event.GREETING_DONE:
        return S.IDENTIFY
    if state is S.IDENTIFY and event is Event.IDENTIFIED:
        return S.UNDERSTAND_INTENT
    if state is S.UNDERSTAND_INTENT and event is Event.INTENT_RECOGNIZED:
        if ctx.intent not in INTENTS:
            return _retry(state, ctx)
        return S.COLLECT_FIELDS if ctx.missing_fields() else S.CONFIRM
    if state is S.COLLECT_FIELDS and event is Event.FIELDS_UPDATED:
        return S.CONFIRM if not ctx.missing_fields() else _retry(state, ctx)
    if state is S.CONFIRM and event is Event.USER_CONFIRMED:
        spec = INTENTS.get(ctx.intent or "")
        if spec is None or ctx.missing_fields():
            return S.FAILSAFE
        return S.CALL_TOOL if spec.tool else S.SAVE_CRM
    if state is S.CONFIRM and event is Event.USER_DENIED:
        return S.COLLECT_FIELDS
    if state is S.CALL_TOOL and event is Event.TOOL_OK:
        return S.REPORT_RESULT
    if state is S.CALL_TOOL and event is Event.TOOL_ERROR:
        return _retry(state, ctx)
    if state is S.REPORT_RESULT and event is Event.RESULT_REPORTED:
        return S.SAVE_CRM
    if state is S.SAVE_CRM and event is Event.CRM_SAVED:
        return S.FINISH
    if state is S.SAVE_CRM and event is Event.CRM_FAILED:
        return _retry(state, ctx) if ctx.retries < SPECS[state].max_retries else S.FAILSAFE
    return state  # event is irrelevant for this state


def next_state(current: S, event: Event, ctx: Context) -> S:
    """Return the next state. Mutates only ctx.retries (reset on state change)."""
    if current in TERMINAL:
        return current
    if event is Event.HANGUP:
        new = S.FINISH
    elif event is Event.OPERATOR_REQUESTED:
        new = S.HANDOFF
    else:
        new = _route(current, event, ctx)
    if new is not current:
        ctx.retries = 0
    return new
