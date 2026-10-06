import json
import re
from typing import Literal
from pydantic import BaseModel, Field, ValidationError, field_validator
from gateway.dialog.specs import SPECS
from gateway.models import DialogState

MAX_REPLY_CHARS = 300
MAX_SENTENCES = 2


class ActionError(ValueError):
    """LLM output is not a safe, valid action."""


class AgentAction(BaseModel):
    model_config = {"extra": "forbid"}
    intent: str = Field(max_length=64)
    fields: dict[str, str] = Field(default_factory=dict)
    next_action: Literal["ask_user", "call_tool", "confirm", "handoff", "finish"]
    tool_name: str | None = None
    tool_args: dict[str, str] = Field(default_factory=dict)
    reply: str = Field(min_length=1)

    @field_validator("reply")
    @classmethod
    def _short_reply(cls, v: str) -> str:
        v = v.strip()
        sentences = [s for s in re.split(r"[.!?]+\s*", v) if s]
        if len(v) > MAX_REPLY_CHARS or len(sentences) > MAX_SENTENCES:
            raise ValueError("reply too long")
        return v


def parse_action(raw: str, state: DialogState) -> AgentAction:
    """Validate raw LLM JSON. The backend, not the model, decides what is allowed."""
    try:
        action = AgentAction.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ActionError(f"invalid action: {type(exc).__name__}") from exc
    if action.next_action == "call_tool":
        if action.tool_name not in SPECS[state].allowed_tools:
            raise ActionError("tool not allowed in this state")
    elif action.tool_name is not None or action.tool_args:
        raise ActionError("tool fields set without call_tool")
    return action
