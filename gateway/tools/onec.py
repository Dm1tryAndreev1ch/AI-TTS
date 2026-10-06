import asyncio
import re
from decimal import Decimal
import httpx
from pydantic import BaseModel, ConfigDict, ValidationError
from gateway.tools.http import Sleep, ToolError, request_json

_ORDER_RE = re.compile(r"^[A-Za-z0-9А-Яа-я\-/]{1,32}$")
_SKU_RE = re.compile(r"^[A-Za-z0-9А-Яа-я\-_.]{1,40}$")
_LAST4_RE = re.compile(r"^\d{4}$")


class OrderStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")
    status: str
    eta: str | None = None

    def speakable(self) -> str:
        base = f"Статус заказа: {self.status[:80]}."
        return base + (f" Ожидаемая дата: {self.eta[:40]}." if self.eta else "")


class StockPrice(BaseModel):
    model_config = ConfigDict(extra="ignore")
    in_stock: bool
    quantity: int | None = None
    price: Decimal | None = None
    currency: str | None = None

    def speakable(self) -> str:
        parts = ["Товар в наличии." if self.in_stock else "Товара нет в наличии."]
        if self.in_stock and self.quantity is not None:
            parts.append(f"Количество: {self.quantity}.")
        if self.price is not None:
            parts.append(f"Цена: {self.price} {self.currency or ''}".strip() + ".")
        return " ".join(parts)


class OneCClient:
    """Read-only 1C HTTP service client: two fixed endpoints, no generic query/execute."""

    def __init__(self, base_url: str, token: str, *, client: httpx.AsyncClient | None = None,
                 timeout: float = 5.0, retries: int = 1, sleep: Sleep = asyncio.sleep) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._retries = retries
        self._sleep = sleep

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, str], label: str) -> dict:
        return await request_json(
            self._client, "GET", f"{self._base}{path}", params=params, headers=self._headers,
            label=label, retries=self._retries, sleep=self._sleep,
        )

    async def get_order_status(self, order_number: str, phone_last4: str) -> OrderStatus:
        if not _ORDER_RE.match(order_number) or not _LAST4_RE.match(phone_last4):
            raise ToolError("invalid order query")
        data = await self._get("/orders/status",
                               {"order": order_number, "phone_last4": phone_last4}, "1c order_status")
        try:
            return OrderStatus.model_validate(data)
        except ValidationError as exc:
            raise ToolError("1c order_status: unexpected response") from exc

    async def get_stock_or_price(self, sku: str) -> StockPrice:
        if not _SKU_RE.match(sku):
            raise ToolError("invalid sku")
        data = await self._get("/stock/price", {"sku": sku}, "1c stock_price")
        try:
            return StockPrice.model_validate(data)
        except ValidationError as exc:
            raise ToolError("1c stock_price: unexpected response") from exc
