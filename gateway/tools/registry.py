from collections.abc import Awaitable, Callable
from typing import Any
from gateway.models import ToolResult
from gateway.tools.http import ToolError
from gateway.tools.onec import OneCClient

Handler = Callable[[dict[str, str]], Awaitable[dict[str, Any]]]


def build_registry(onec: OneCClient) -> dict[str, Handler]:
    async def order_status(args: dict[str, str]) -> dict[str, Any]:
        r = await onec.get_order_status(args.get("order_number", ""), args.get("phone_last4", ""))
        return {"speech": r.speakable()}

    async def stock_price(args: dict[str, str]) -> dict[str, Any]:
        r = await onec.get_stock_or_price(args.get("sku", ""))
        return {"speech": r.speakable()}

    return {"get_order_status": order_status, "get_stock_or_price": stock_price}


async def run_tool(registry: dict[str, Handler], name: str, args: dict[str, str]) -> ToolResult:
    """Only registered tools run; failures become short ToolResult errors."""
    handler = registry.get(name)
    if handler is None:
        return ToolResult(ok=False, error="unknown_tool")
    try:
        return ToolResult(ok=True, data=await handler(args))
    except ToolError as exc:
        return ToolResult(ok=False, error="tool_unavailable" if exc.retryable else "tool_rejected")
