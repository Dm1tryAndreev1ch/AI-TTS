#!/usr/bin/env bash
# Voice extras on macOS: microphone, Silero VAD, faster-whisper, Piper and a Russian Piper voice.
# Run scripts/setup_mac.sh first.
set -euo pipefail

[ -d .venv ] || { echo "Run scripts/setup_mac.sh first"; exit 1; }
. .venv/bin/activate

pip install -e '.[voice]'

mkdir -p models
(cd models && python -m piper.download_voices ru_RU-irina-medium) \
  || echo "Voice download failed: download a Russian Piper voice manually into models/ and set PIPER_VOICE in .env"

echo
echo "Done. Run the voice demo:  . .venv/bin/activate && python -m gateway.voice_cli"
echo "macOS will ask for microphone access for your terminal on the first run."
