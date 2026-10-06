from dataclasses import dataclass
from gateway.models import DialogState as S


@dataclass(frozen=True)
class StateSpec:
    required_fields: tuple[str, ...]
    allowed_tools: frozenset[str]
    max_retries: int


@dataclass(frozen=True)
class IntentSpec:
    required_fields: tuple[str, ...]
    tool: str | None


# Required fields per intent; the tool is a read-only 1C call or None.
INTENTS: dict[str, IntentSpec] = {
    "order_status": IntentSpec(("order_number", "phone_last4"), "get_order_status"),
    "price_stock": IntentSpec(("sku",), "get_stock_or_price"),
    "callback": IntentSpec(("name", "phone"), None),
}

_NO_TOOLS: frozenset[str] = frozenset()

SPECS: dict[S, StateSpec] = {
    S.GREETING: StateSpec((), _NO_TOOLS, 1),
    S.IDENTIFY: StateSpec(("phone",), _NO_TOOLS, 2),
    S.UNDERSTAND_INTENT: StateSpec((), _NO_TOOLS, 2),
    S.COLLECT_FIELDS: StateSpec((), _NO_TOOLS, 3),
    S.CONFIRM: StateSpec((), _NO_TOOLS, 2),
    S.CALL_TOOL: StateSpec((), frozenset(t.tool for t in INTENTS.values() if t.tool), 2),
    S.REPORT_RESULT: StateSpec((), _NO_TOOLS, 1),
    S.SAVE_CRM: StateSpec((), frozenset({"crm_save"}), 2),
    S.HANDOFF: StateSpec((), _NO_TOOLS, 0),
    S.FINISH: StateSpec((), _NO_TOOLS, 0),
    S.FAILSAFE: StateSpec((), _NO_TOOLS, 0),
}

TERMINAL = frozenset({S.HANDOFF, S.FINISH, S.FAILSAFE})
