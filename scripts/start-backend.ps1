$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendRoot = Join-Path $ProjectRoot "backend"
$BackendPython = Join-Path $BackendRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $BackendPython)) {
    throw "Backend environment is missing. Run scripts\setup.ps1 first."
}
if (-not (Test-Path (Join-Path $BackendRoot ".env"))) {
    throw "backend/.env is missing. Copy backend/.env.example and add your Azure configuration."
}

Set-Location $BackendRoot
& $BackendPython -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
