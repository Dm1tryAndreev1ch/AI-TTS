# Voice extras on Windows: microphone, Silero VAD, faster-whisper, Piper and a Russian Piper voice.
# Run scripts\setup_windows.ps1 first, then from the repository root:
#   powershell -ExecutionPolicy Bypass -File scripts\setup_voice_windows.ps1
$ErrorActionPreference = "Continue"

$venvPython = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Run scripts\setup_windows.ps1 first" -ForegroundColor Red
    exit 1
}

& $venvPython -m pip install -e ".[voice]"
if ($LASTEXITCODE -ne 0) {
    Write-Host "pip install failed. If the error mentions ctranslate2 or torch, check that the venv uses Python 3.12 (python --version inside .venv)." -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force models | Out-Null
Push-Location models
& ..\.venv\Scripts\python.exe -m piper.download_voices ru_RU-irina-medium
$voiceOk = ($LASTEXITCODE -eq 0)
Pop-Location
if (-not $voiceOk) {
    Write-Host "Voice download failed: download a Russian Piper voice manually into models\ and set PIPER_VOICE in .env" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Done. Voice demo:  powershell -ExecutionPolicy Bypass -File scripts\run_windows.ps1 -Mode voice"
