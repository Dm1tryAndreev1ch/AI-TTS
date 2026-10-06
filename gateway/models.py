from enum import StrEnum
from uuid import UUID
from pydantic import BaseModel, Field

class DialogState(StrEnum):
    GREETING = 'GREETING'
    IDENTIFY = 'IDENTIFY'
    UNDERSTAND_INTENT = 'UNDERSTAND_INTENT'
    COLLECT_FIELDS = 'COLLECT_FIELDS'
    CONFIRM = 'CONFIRM'
    CALL_TOOL = 'CALL_TOOL'
    REPORT_RESULT = 'REPORT_RESULT'
    SAVE_CRM = 'SAVE_CRM'
    HANDOFF = 'HANDOFF'
    FINISH = 'FINISH'
    FAILSAFE = 'FAILSAFE'

class CallSession(BaseModel):
    call_id: UUID
    state: DialogState = DialogState.GREETING
    received_bytes: int = 0

class ToolCall(BaseModel):
    name: str
    arguments: dict = Field(default_factory=dict)

class ToolResult(BaseModel):
    ok: bool
    data: dict = Field(default_factory=dict)
    error: str | None = None
