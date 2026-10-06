import logging
import re
import time
from typing import Protocol
from gateway.dialog.actions import ActionError, parse_action
from gateway.dialog.machine import Context, Event, next_state
from gateway.dialog.specs import INTENTS, TERMINAL
from gateway.models import DialogState as S
from gateway.tools.registry import Handler, run_tool

log = logging.getLogger("gateway.orchestrator")

OPERATOR_RE = re.compile(r"оператор|человек|соедин|менеджер")
YES_RE = re.compile(r"\b(да|верно|правильно|подтверждаю|ага|угу)\b")
NO_RE = re.compile(r"\b(нет|неверно|неправильно|не так)\b")

GREETING = "Здравствуйте!"
FIELD_PROMPTS = {
    "order_number": "Назовите номер заказа.",
    "phone_last4": "Назовите последние четыре цифры вашего телефона.",
    "sku": "Назовите артикул товара.",
    "name": "Как вас зовут?",
    "phone": "Назовите номер телефона для связи.",
}
FIELD_LABELS = {
    "order_number": "номер заказа", "phone_last4": "последние цифры телефона",
    "sku": "артикул", "name": "имя", "phone": "телефон",
}
SAY_REPEAT = "Не расслышал."
SAY_HANDOFF = "Соединяю вас с сотрудником. Пожалуйста, подождите."
SAY_FAILSAFE = "Извините, произошла ошибка. Мы перезвоним вам."
SAY_BYE = "Спасибо за звонок. До свидания!"


class Llm(Protocol):
    async def decide(self, state: S, ctx: Context, user_text: str) -> str: ...


class Speaker(Protocol):
    async def say(self, text: str) -> None: ...


class CrmSink(Protocol):
    async def save_call(self, call_id: str, ctx: Context, transcript: list[tuple[str, str]],
                        duration_sec: int, outcome: str) -> None: ...


class CallOrchestrator:
    """Drives one call. The LLM only proposes intent/fields; every spoken
    sentence except tool results is a fixed template, and tools run only via the registry."""

    def __init__(self, call_id: str, llm: Llm, speaker: Speaker, tools: dict[str, Handler],
                 crm: CrmSink, caller_phone: str | None = None) -> None:
        self.call_id = call_id
        self.llm, self.speaker, self.tools, self.crm = llm, speaker, tools, crm
        self.caller_phone = caller_phone
        self.state = S.GREETING
        self.ctx = Context()
        self.transcript: list[tuple[str, str]] = []
        self._started = time.monotonic()
        self._speech: str | None = None

    @property
    def finished(self) -> bool:
        return self.state in TERMINAL

    async def _say(self, text: str) -> None:
        self.transcript.append(("agent", text))
        await self.speaker.say(text)

    async def start(self) -> None:
        await self._say(GREETING)
        await self._dispatch(Event.GREETING_DONE)

    async def hangup(self) -> None:
        if not self.finished:
            await self._dispatch(Event.HANGUP)

    async def on_silence(self) -> None:
        if not self.finished:
            await self._dispatch(Event.SILENCE)

    async def handle_user_text(self, text: str) -> None:
        if self.finished or not text.strip():
            return
        self.transcript.append(("user", text))
        lowered = text.lower()
        if OPERATOR_RE.search(lowered):
            await self._dispatch(Event.OPERATOR_REQUESTED)
            return
        event: Event | None = None
        if self.state is S.IDENTIFY:
            digits = re.sub(r"\D", "", text)
            if len(digits) >= 7:
                self.ctx.fields["phone"] = "+" + digits
                event = Event.IDENTIFIED
            else:
                event = Event.UNCLEAR
        elif self.state in (S.UNDERSTAND_INTENT, S.COLLECT_FIELDS):
            event = await self._llm_event(text)
        elif self.state is S.CONFIRM:
            event = Event.USER_CONFIRMED if YES_RE.search(lowered) else (
                Event.USER_DENIED if NO_RE.search(lowered) else Event.UNCLEAR)
        if event is not None:
            await self._dispatch(event)

    async def _llm_event(self, text: str) -> Event:
        try:
            raw = await self.llm.decide(self.state, self.ctx, text)
            action = parse_action(raw, self.state)
        except ActionError:
            return Event.UNCLEAR
        except Exception as exc:  # LLM backend down: treat as unclear, never crash the call
            log.warning("llm_failed %s", type(exc).__name__)
            return Event.UNCLEAR
        if action.next_action == "handoff":
            return Event.OPERATOR_REQUESTED
        if action.next_action == "call_tool":
            return Event.UNCLEAR  # tools are chosen by the backend, never by the model
        if self.state is S.UNDERSTAND_INTENT:
            self.ctx.intent = action.intent
        spec = INTENTS.get(self.ctx.intent or "")
        if spec:
            for key, value in action.fields.items():
                if key in spec.required_fields and value.strip():
                    self.ctx.fields[key] = value.strip()[:64]
        return Event.INTENT_RECOGNIZED if self.state is S.UNDERSTAND_INTENT else Event.FIELDS_UPDATED

    async def _dispatch(self, event: Event | None) -> None:
        for _ in range(12):  # guard against loops
            if event is None:
                return
            prev = self.state
            self.state = next_state(prev, event, self.ctx)
            event = await self._enter(prev, event)

    async def _enter(self, prev: S, event: Event) -> Event | None:
        s = self.state
        retry = s is prev and event in (Event.UNCLEAR, Event.SILENCE, Event.FIELDS_UPDATED)
        prefix = SAY_REPEAT + " " if retry else ""
        if s is S.IDENTIFY:
            if prev is S.GREETING and self.caller_phone:
                self.ctx.fields["phone"] = self.caller_phone
                return Event.IDENTIFIED
            await self._say(prefix + "Назовите, пожалуйста, ваш номер телефона.")
        elif s is S.UNDERSTAND_INTENT:
            await self._say(prefix + "Чем могу помочь?")
        elif s is S.COLLECT_FIELDS:
            missing = self.ctx.missing_fields()
            await self._say(prefix + (FIELD_PROMPTS[missing[0]] if missing else "Уточните, пожалуйста."))
        elif s is S.CONFIRM:
            spec = INTENTS[self.ctx.intent or ""]
            parts = ", ".join(f"{FIELD_LABELS[f]}: {self.ctx.fields[f]}" for f in spec.required_fields)
            await self._say(f"Проверьте: {parts}. Всё верно?")
        elif s is S.CALL_TOOL:
            spec = INTENTS[self.ctx.intent or ""]
            args = {f: self.ctx.fields[f] for f in spec.required_fields}
            result = await run_tool(self.tools, spec.tool or "", args)
            if result.ok:
                self._speech = str(result.data.get("speech", ""))
                return Event.TOOL_OK
            return Event.TOOL_ERROR
        elif s is S.REPORT_RESULT:
            await self._say(self._speech or "Готово.")
            return Event.RESULT_REPORTED
        elif s is S.SAVE_CRM:
            return await self._save("resolved", Event.CRM_SAVED, Event.CRM_FAILED, strict=True)
        elif s is S.FINISH:
            if event is not Event.HANGUP:
                await self._say(SAY_BYE)
        elif s is S.HANDOFF:
            await self._say(SAY_HANDOFF)
            await self._save("handoff", None, None, strict=False)
        elif s is S.FAILSAFE:
            await self._say(SAY_FAILSAFE)
        return None

    async def _save(self, outcome: str, ok: Event | None, fail: Event | None, *, strict: bool) -> Event | None:
        if not strict and not self.ctx.fields.get("phone"):
            return None
        try:
            await self.crm.save_call(self.call_id, self.ctx, list(self.transcript),
                                     int(time.monotonic() - self._started), outcome)
        except Exception as exc:
            log.warning("crm_save_failed %s", type(exc).__name__)
            return fail
        return ok
