# One-time setup on Windows 10/11. Run from the repository root:
#   powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
# Installs Ollama (via winget), creates .venv, installs the project and pulls the LLM.
$ErrorActionPreference = "Continue"

function Fail($message) {
    Write-Host $message -ForegroundColor Red
    exit 1
}

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Fail "Python launcher 'py' not found. Install Python 3.12 from https://www.python.org/downloads/windows/ and run this script again."
}

$pyVersion = $null
foreach ($v in @("3.12", "3.11")) {
    & py "-$v" -c "import sys" 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $pyVersion = $v; break }
}
if (-not $pyVersion) {
    Fail "Python 3.11 or 3.12 is required (3.12 recommended: some voice dependencies may have no wheels for 3.13)."
}
Write-Host "Using Python $pyVersion"

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail "Ollama not found. Install it from https://ollama.com/download/windows and run this script again."
    }
    winget install -e --id Ollama.Ollama
    if ($LASTEXITCODE -ne 0) {
        Fail "winget could not install Ollama. Install it from https://ollama.com/download/windows"
    }
    Write-Host "Ollama installed. Open a NEW PowerShell window and run this script again." -ForegroundColor Yellow
    exit 0
}

& py "-$pyVersion" -m venv .venv
if ($LASTEXITCODE -ne 0) { Fail "Could not create .venv" }
$venvPython = ".\.venv\Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -e ".[test]"
if ($LASTEXITCODE -ne 0) { Fail "pip install failed" }

if (-not (Test-Path .env)) { Copy-Item .env.example .env }

$model = if ($env:OLLAMA_MODEL) { $env:OLLAMA_MODEL } else { "qwen2.5:7b" }
Write-Host "Pulling model $model (several GB)..."
ollama pull $model
if ($LASTEXITCODE -ne 0) {
    Fail "Could not pull the model. Make sure Ollama is running (start it from the Start menu) and run: ollama pull $model"
}

Write-Host ""
Write-Host "Done. Text demo:  powershell -ExecutionPolicy Bypass -File scripts\run_windows.ps1"
