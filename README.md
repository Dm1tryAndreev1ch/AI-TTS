# AI-TTS

Локальный голосовой агент для входящих звонков: Asterisk AudioSocket + Python/FastAPI, Bitrix24 и 1С. Прототип, не для клиентских звонков.

## Что реализовано

- `gateway/protocol.py`, `gateway/server.py`: TCP-сервер AudioSocket, UUID сессии, приём PCM16 8 kHz, echo-режим, лимит подключений, таймаут.
- `gateway/dialog/`: state machine (11 состояний, лимиты повторов, переход к оператору) и валидатор JSON-ответов LLM.
- `gateway/tools/`: клиент Bitrix24 (webhook), клиент 1С только для чтения, реестр разрешённых инструментов, общий HTTP-слой с retry.
- `gateway/orchestrator.py`: ведёт один звонок. LLM лишь предлагает намерение и поля; все реплики, кроме ответа 1С, берутся из фиксированных шаблонов; инструменты вызывает только backend.
- `gateway/crm_sink.py`: сохранение звонка в Bitrix24 (контакт, сделка, комментарий в таймлайне).
- Тесты используют заглушки LLM, речи и HTTP; реальные Bitrix24, 1С и Asterisk в них не участвуют.

## Что НЕ реализовано

- Silero VAD, faster-whisper, Ollama, Piper: есть только интерфейсы `Llm` и `Speaker` в оркестраторе.
- Подключение оркестратора к `server.py`: аудио пока принимается, но не распознаётся и не озвучивается.
- Barge-in (перебивание), реальный перевод звонка на оператора в Asterisk (сейчас только фраза и запись в CRM).
- Проверка на реальном звонке и на целевом железе; задержки не измерены.

## Запуск транспорта

```sh
cp .env.example .env
docker compose up --build
```

Gateway слушает TCP 9092, health: localhost:8000/health. Нужен один процесс Uvicorn: сессии хранятся в памяти. Порты привязаны к localhost; AudioSocket не имеет аутентификации и TLS, не публикуйте его в Интернет.

## Asterisk

Asterisk ставится отдельно на тот же хост. Проверьте, что в сборке есть приложение AudioSocket и функция UUID. Добавьте контекст из `asterisk/extensions.conf` в dialplan, а `asterisk/pjsip.conf.example` используйте только в лаборатории (замените CHANGE_ME). Зарегистрируйте softphone как 6001 и наберите 700. Для проверки двустороннего звука задайте `ECHO_AUDIO=true` и используйте наушники.

## Контракт с 1С

HTTP-сервис в 1С должен отдавать JSON:

- `GET /orders/status?order=...&phone_last4=...` -> `{"status": "...", "eta": "..."}`
- `GET /stock/price?sku=...` -> `{"in_stock": true, "quantity": 5, "price": "199.90", "currency": "BYN"}`

Авторизация: заголовок `Authorization: Bearer <token>`.

## Bitrix24

Используется входящий webhook. Фильтр `PHONE` в `crm.contact.list` работает только по точному совпадению, поэтому храните номера в одном формате, например `+375291112233`. Транскрипт звонка содержит персональные данные: убедитесь, что вправе его хранить. Секреты храните в `.env`, не в Git.

## Тесты

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
pytest
```

## Следующие шаги

1. Реализовать `Llm` через Ollama, `Speaker` через Piper, VAD и STT; подключить оркестратор к `server.py`.
2. Проверить реальный звонок и измерить задержки.
3. Добавить barge-in и перевод на оператора в Asterisk.
4. Проверить интеграции на реальных Bitrix24 и 1С.
