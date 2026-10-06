import asyncio
import re
from typing import Any
import httpx
from pydantic import BaseModel
from gateway.tools.http import Sleep, ToolError, request_json

_PHONE_RE = re.compile(r"^\+?\d{7,15}$")


class Contact(BaseModel):
    id: int
    name: str | None = None


class Bitrix24Client:
    """Bitrix24 REST via an inbound webhook. The webhook URL is a secret and is never logged."""

    def __init__(
        self,
        webhook_url: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 5.0,
        retries: int = 2,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._base = webhook_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._retries = retries
        self._sleep = sleep
        self._done: dict[str, Any] = {}  # in-process idempotency cache

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, payload: dict) -> Any:
        data = await request_json(
            self._client, "POST", f"{self._base}/{method}.json", json=payload,
            label=f"bitrix24 {method}", retries=self._retries, sleep=self._sleep,
        )
        if "error" in data:
            raise ToolError(f"bitrix24 {method}: API error {str(data['error'])[:40]}")
        if "result" not in data:
            raise ToolError(f"bitrix24 {method}: missing result")
        return data["result"]

    async def _once(self, key: str | None, make):
        if key is not None and key in self._done:
            return self._done[key]
        result = await make()
        if key is not None:
            self._done[key] = result
        return result

    @staticmethod
    def _phone(phone: str) -> str:
        cleaned = re.sub(r"[\s\-()]", "", phone)
        if not _PHONE_RE.match(cleaned):
            raise ToolError("invalid phone")
        return cleaned

    async def find_contact_by_phone(self, phone: str) -> Contact | None:
        # The PHONE filter matches exactly, so the caller must pass the stored format.
        result = await self._call("crm.contact.list", {
            "filter": {"PHONE": self._phone(phone)}, "select": ["ID", "NAME"], "start": 0,
        })
        if not result:
            return None
        row = result[0]
        return Contact(id=int(row["ID"]), name=row.get("NAME"))

    async def create_contact(self, name: str, phone: str, company: str | None = None,
                             *, idempotency_key: str | None = None) -> Contact:
        fields: dict[str, Any] = {
            "NAME": name[:100], "PHONE": [{"VALUE": self._phone(phone), "VALUE_TYPE": "WORK"}],
        }
        if company:
            fields["COMPANY_TITLE"] = company[:100]

        async def make() -> Contact:
            return Contact(id=int(await self._call("crm.contact.add", {"fields": fields})), name=name)

        return await self._once(idempotency_key and f"contact:{idempotency_key}", make)

    async def update_contact(self, contact_id: int, fields: dict[str, Any]) -> bool:
        allowed = {"NAME", "LAST_NAME", "COMPANY_TITLE", "COMMENTS"}
        bad = set(fields) - allowed
        if bad:
            raise ToolError("field not allowed")
        return bool(await self._call("crm.contact.update", {"id": contact_id, "fields": fields}))

    async def create_deal(self, contact_id: int, title: str, summary: str, source: str,
                          *, idempotency_key: str | None = None) -> int:
        fields = {
            "TITLE": title[:200], "CONTACT_IDS": [contact_id],
            "COMMENTS": summary[:2000], "SOURCE_DESCRIPTION": source[:200],
        }

        async def make() -> int:
            return int(await self._call("crm.deal.add", {"fields": fields}))

        return await self._once(idempotency_key and f"deal:{idempotency_key}", make)

    async def add_activity(self, entity_id: int, summary: str, transcript: str, duration_sec: int,
                           *, entity_type: str = "deal", idempotency_key: str | None = None) -> int:
        text = f"{summary}\nДлительность: {duration_sec} с\n\n{transcript}"[:8000]

        async def make() -> int:
            return int(await self._call("crm.timeline.comment.add", {"fields": {
                "ENTITY_ID": entity_id, "ENTITY_TYPE": entity_type, "COMMENT": text,
            }}))

        return await self._once(idempotency_key and f"activity:{idempotency_key}", make)
