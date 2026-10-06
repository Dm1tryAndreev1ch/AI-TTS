import json
import httpx
from gateway.dialog.machine import Context
from gateway.dialog.specs import INTENTS
from gateway.models import DialogState
from gateway.tools.http import ToolError, request_json

INTENT_HELP = {
    "order_status": "статус заказа клиента",
    "price_stock": "цена или наличие товара по артикулу",
    "callback": "заказать обратный звонок",
}

# The model may never pick call_tool: tools are chosen by the backend only.
SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": [*INTENTS, "unknown"]},
        "fields": {"type": "object", "additionalProperties": {"type": "string"}},
        "next_action": {"type": "string", "enum": ["ask_user", "confirm", "handoff", "finish"]},
        "reply": {"type": "string"},
    },
    "required": ["intent", "fields", "next_action", "reply"],
}


def _system_prompt() -> str:
    lines = [f"- {name}: {INTENT_HELP.get(name, name)}; поля: {', '.join(spec.required_fields)}"
             for name, spec in INTENTS.items()]
    return (
        "Ты модуль понимания речи голосового ассистента компании. Клиент говорит по-русски, "
        "текст получен распознаванием речи и может содержать ошибки.\n"
        "Верни только JSON по заданной схеме.\n"
        "Допустимые намерения:\n" + "\n".join(lines) + "\n- unknown: намерение не удалось понять\n"
        "Правила:\n"
        "- В fields клади только значения, которые клиент явно назвал. Не угадывай и не выдумывай.\n"
        "- Ключи fields только из списка полей выбранного намерения.\n"
        "- Если клиент просит оператора или человека, верни next_action=handoff.\n"
        "- reply: не более двух коротких предложений на русском."
    )


def build_messages(state: DialogState, ctx: Context, user_text: str) -> list[dict[str, str]]:
    known = {k: v for k, v in ctx.fields.items() if k != "phone"}  # keep caller phone out of the prompt
    user = (
        f"Состояние диалога: {state.value}\n"
        f"Текущее намерение: {ctx.intent or 'не определено'}\n"
        f"Уже известные поля: {json.dumps(known, ensure_ascii=False)}\n"
        f"Реплика клиента: {user_text}"
    )
    return [{"role": "system", "content": _system_prompt()}, {"role": "user", "content": user}]


class OllamaLlm:
    """Local Ollama client: structured JSON output, temperature 0, model kept loaded."""

    def __init__(self, base_url: str = "http://127.0.0.1:11434", model: str = "qwen2.5:7b", *,
                 client: httpx.AsyncClient | None = None, timeout: float = 60.0,
                 think: bool | None = None) -> None:
        self._base = base_url.rstrip("/")
        self.model = model
        self._think = think
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def check(self) -> None:
        """Fail early with a clear message if Ollama is down or the model is not pulled."""
        data = await request_json(self._client, "GET", f"{self._base}/api/tags",
                                  label="ollama tags", retries=0)
        names = {m.get("name") for m in data.get("models", []) if isinstance(m, dict)}
        if self.model not in names and f"{self.model}:latest" not in names:
            raise ToolError(f"model {self.model} is not pulled; run: ollama pull {self.model}")

    async def decide(self, state: DialogState, ctx: Context, user_text: str) -> str:
        payload: dict = {
            "model": self.model, "stream": False, "format": SCHEMA, "keep_alive": "30m",
            "options": {"temperature": 0}, "messages": build_messages(state, ctx, user_text),
        }
        if self._think is not None:
            payload["think"] = self._think
        data = await request_json(self._client, "POST", f"{self._base}/api/chat",
                                  json=payload, label="ollama chat", retries=0)
        content = (data.get("message") or {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise ToolError("ollama chat: empty response")
        return content
