# AI-TTS

Локальный голосовой агент для входящих звонков: Asterisk AudioSocket + Python, Ollama, faster-whisper, Piper, Bitrix24 и 1С. Прототип, не для клиентских звонков.

## Режимы запуска

| Режим | Команда | Документация |
|---|---|---|
| Текст в консоли | `python -m gateway.cli` | [docs/MAC.md](docs/MAC.md) |
| Голос на ноутбуке (микрофон, динамики) | `python -m gateway.voice_cli` | [docs/MAC.md](docs/MAC.md) |
| Телефония Asterisk | `python -m gateway.telephony_cli` | [docs/TELEPHONY.md](docs/TELEPHONY.md) |
| Только транспорт (приём аудио, echo) | `docker compose up --build` | ниже |

## Что реализовано

- `gateway/server.py`, `gateway/audiosocket.py`, `gateway/protocol.py`: TCP-сервер AudioSocket, обработчик на каждый звонок, пасинг аудио 20 мс, лимит подключений, таймаут.
- `gateway/telephony/`: мост между звонком и голосовым циклом, ресемплинг 8 кГц ↔ 16 кГц.
- `gateway/voice/`: разбиение речи на реплики, Silero VAD, faster-whisper, Piper, микрофон.
- `gateway/dialog/`: state machine (11 состояний, лимиты повторов, переход к оператору) и валидатор JSON-ответов LLM.
- `gateway/orchestrator.py`: ведёт один звонок. LLM лишь предлагает намерение и поля; все реплики, кроме ответа 1С, берутся из шаблонов; инструменты вызывает только backend.
- `gateway/llm_ollama.py`: локальная LLM со структурированным JSON.
- `gateway/tools/`, `gateway/crm_sink.py`, `gateway/backends.py`: Bitrix24 (webhook), 1С только для чтения, реестр разрешённых инструментов, сохранение звонка в CRM.

## Что НЕ реализовано или не проверено

- Всё проверялось тестами с заглушками: реальные Ollama, Silero, faster-whisper, Piper, микрофон, Asterisk, Bitrix24 и 1С в тестах не участвуют. Качество распознавания русской речи и задержки не измерены.
- Перебивание (barge-in): режим полудуплексный.
- Реальный перевод звонка на оператора в Asterisk (сейчас только фраза, запись в CRM и завершение звонка).
- Номер звонящего из AudioSocket (агент спрашивает его голосом) и несколько одновременных звонков.

## Транспорт в Docker

```sh
cp .env.example .env
docker compose up --build
```

Поднимает только приём аудио (TCP 9092, health: localhost:8000/health), без моделей. Порты привязаны к localhost; AudioSocket не имеет аутентификации и TLS, не публикуйте его в Интернет.

## Контракт с 1С

HTTP-сервис в 1С должен отдавать JSON:

- `GET /orders/status?order=...&phone_last4=...` -> `{"status": "...", "eta": "..."}`
- `GET /stock/price?sku=...` -> `{"in_stock": true, "quantity": 5, "price": "199.90", "currency": "BYN"}`

Авторизация: заголовок `Authorization: Bearer <token>`.

## Bitrix24

Используется входящий webhook. Фильтр `PHONE` в `crm.contact.list` работает только по точному совпадению, поэтому храните номера в одном формате, например `+375291112233`. Транскрипт звонка содержит персональные данные: убедитесь, что вправе его хранить. Секреты храните в `.env`, не в Git. Лицензии: Piper распространяется по GPL, у голосов свои лицензии.

## Тесты

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test,voice]'
pytest
```
