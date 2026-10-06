from gateway.dialog.machine import Context
from gateway.tools.bitrix24 import Bitrix24Client
from gateway.tools.http import ToolError


class BitrixCrmSink:
    """Saves a finished call to Bitrix24: contact -> deal -> timeline comment.
    The transcript contains personal data; make sure you may store it before enabling."""

    def __init__(self, client: Bitrix24Client) -> None:
        self._bx = client

    async def save_call(self, call_id: str, ctx: Context, transcript: list[tuple[str, str]],
                        duration_sec: int, outcome: str) -> None:
        phone = ctx.fields.get("phone")
        if not phone:
            raise ToolError("no phone to identify contact")
        contact = await self._bx.find_contact_by_phone(phone)
        if contact is None:
            name = ctx.fields.get("name") or f"Клиент {phone}"
            contact = await self._bx.create_contact(name, phone, idempotency_key=call_id)
        summary = "; ".join(f"{k}: {v}" for k, v in ctx.fields.items() if k != "phone") or outcome
        deal_id = await self._bx.create_deal(
            contact.id, f"Звонок: {ctx.intent or 'неизвестно'} ({outcome})", summary,
            "voice-agent", idempotency_key=call_id)
        text = "\n".join(f"{role}: {line}" for role, line in transcript)
        await self._bx.add_activity(deal_id, summary, text, duration_sec, idempotency_key=call_id)
