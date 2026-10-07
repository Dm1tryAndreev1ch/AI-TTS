# Run the demo on Windows from the repository root:
#   powershell -ExecutionPolicy Bypass -File scripts\run_windows.ps1            (text mode)
#   powershell -ExecutionPolicy Bypass -File scripts\run_windows.ps1 -Mode voice
param([ValidateSet("text", "voice")][string]$Mode = "text")

$venvPython = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Run scripts\setup_windows.ps1 first" -ForegroundColor Red
    exit 1
}

if ($Mode -eq "voice") {
    & $venvPython -m gateway.voice_cli
} else {
    & $venvPython -m gateway.cli
}
