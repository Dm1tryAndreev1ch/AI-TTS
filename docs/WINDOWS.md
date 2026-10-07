# Запуск на Windows 10/11

## Требования

- Windows 10 22H2 или новее (требование Ollama).
- Python 3.12 с python.org вместе с `py` launcher (подходит и 3.11). Не берите 3.13: по данным одного из руководств, у ctranslate2 (основа faster-whisper) нет сборок для 3.13. Это не проверялось нами.
- Для голоса: микрофон и наушники. Рекомендуется 16 ГБ памяти.

## Шаг 1: текстовый режим

```powershell
git clone https://github.com/Dm1tryAndreev1ch/AI-TTS.git
cd AI-TTS
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
powershell -ExecutionPolicy Bypass -File scripts\run_windows.ps1
```

Скрипт устанавливает Ollama через `winget install -e --id Ollama.Ollama`. Если Ollama уже была не установлена, после установки откройте новое окно PowerShell и запустите скрипт ещё раз: путь к `ollama` появляется только в новой сессии. Если загрузка модели не сработала, запустите Ollama из меню «Пуск» и выполните `ollama pull qwen2.5:7b`.

Пример: напишите `сколько стоит артикул X-1`, затем `да` на вопрос о подтверждении. Без `ONEC_URL` и `BITRIX_WEBHOOK` используются выдуманные демо-данные 1С и вывод CRM в консоль.

## Шаг 2: голосовой режим

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_voice_windows.ps1
powershell -ExecutionPolicy Bypass -File scripts\run_windows.ps1 -Mode voice
```

Микрофон читает sounddevice, звук проигрывается встроенным модулем `winsound` (выбирается автоматически, `VOICE_PLAYER` можно оставить пустым). Если микрофон не работает, проверьте в настройках Windows раздел «Конфиденциальность → Микрофон». При первом запуске faster-whisper скачивает модель распознавания из интернета. Режим полудуплексный, используйте наушники.

## Видеокарта

- Ollama сам использует поддерживаемую видеокарту. Для NVIDIA в документации Ollama указаны драйверы 551.61 и новее. Проверка: `ollama ps`.
- Распознавание речи в проекте всегда работает на CPU. Ускорение на NVIDIA потребует CUDA 12 и cuDNN 9 и правки кода, этого в проекте нет.

## Телефония

Asterisk на Windows не рекомендуется. Для телефонии используйте Linux-хост (см. [docs/TELEPHONY.md](TELEPHONY.md)), а Windows оставьте для разработки.

## Что не проверялось

PowerShell-скрипты и запуск на реальной Windows не проверялись: в среде разработки нет PowerShell. CI прогоняет на `windows-latest` только тесты. Имя голоса `ru_RU-irina-medium` и путь `models\ru_RU-irina-medium.onnx` тоже не проверялись: если загрузка не сработала, скачайте русский голос вручную в `models\` и укажите `PIPER_VOICE`. Качество распознавания русской речи и задержку измерьте сами.
