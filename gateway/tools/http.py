import asyncio
from collections.abc import Awaitable, Callable
import httpx


class ToolError(Exception):
    """Safe error: never contains URLs, tokens or response bodies."""

    def __init__(self, message: str, *, retryable: bool = False, status: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status = status


Sleep = Callable[[float], Awaitable[None]]


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    label: str,
    retries: int = 2,
    base_delay: float = 0.3,
    sleep: Sleep = asyncio.sleep,
    **kwargs,
) -> dict:
    """Send a request, retry transport errors/429/5xx with exponential backoff."""
    last: ToolError | None = None
    for attempt in range(retries + 1):
        if attempt:
            await sleep(base_delay * 2 ** (attempt - 1))
        try:
            resp = await client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            last = ToolError(f"{label}: transport error {type(exc).__name__}", retryable=True)
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            last = ToolError(f"{label}: HTTP {resp.status_code}", retryable=True, status=resp.status_code)
            continue
        if resp.status_code >= 400:
            raise ToolError(f"{label}: HTTP {resp.status_code}", status=resp.status_code)
        try:
            data = resp.json()
        except ValueError as exc:
            raise ToolError(f"{label}: invalid JSON") from exc
        if not isinstance(data, dict):
            raise ToolError(f"{label}: unexpected response shape")
        return data
    assert last is not None
    raise last
