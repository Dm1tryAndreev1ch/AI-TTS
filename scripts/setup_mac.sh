#!/usr/bin/env bash
# One-time setup on macOS (Apple Silicon). Installs Ollama, a Python venv and pulls the LLM.
set -euo pipefail

command -v brew >/dev/null || { echo "Install Homebrew first: https://brew.sh"; exit 1; }

PY=python3
if command -v python3.12 >/dev/null; then PY=python3.12; fi
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Python 3.11+ required, installing python@3.12"
  brew install python@3.12
  PY=python3.12
fi

brew list ollama >/dev/null 2>&1 || brew install ollama
brew services start ollama

"$PY" -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e '.[test]'

[ -f .env ] || cp .env.example .env
MODEL="${OLLAMA_MODEL:-qwen2.5:7b}"
echo "Pulling model $MODEL (several GB)..."
ollama pull "$MODEL"

echo
echo "Done. Run the text demo:  . .venv/bin/activate && python -m gateway.cli"
