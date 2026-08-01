[CmdletBinding()]
param(
    [string]$PythonCommand = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendRoot = Join-Path $ProjectRoot "backend"
$FrontendRoot = Join-Path $ProjectRoot "frontend"
$BackendPython = Join-Path $BackendRoot ".venv\Scripts\python.exe"

Write-Host "Preparing CareTranslate Studio..." -ForegroundColor Cyan

if (-not (Test-Path (Join-Path $BackendRoot ".env"))) {
    Copy-Item (Join-Path $BackendRoot ".env.example") (Join-Path $BackendRoot ".env")
    Write-Host "Created backend/.env - add your Azure endpoints and keys there." -ForegroundColor Yellow
}

if (-not (Test-Path $BackendPython)) {
    & $PythonCommand -m venv (Join-Path $BackendRoot ".venv")
}
& $BackendPython -m pip install -r (Join-Path $BackendRoot "requirements-dev.txt")

if (-not (Test-Path (Join-Path $FrontendRoot ".env.local"))) {
    Copy-Item (Join-Path $FrontendRoot ".env.local.example") (Join-Path $FrontendRoot ".env.local")
}

Push-Location $FrontendRoot
try {
    npm ci
}
finally {
    Pop-Location
}

Write-Host "Setup complete." -ForegroundColor Green
Write-Host "1. Add Azure values to backend/.env"
Write-Host "2. Run scripts\run-poc.ps1, or start the backend and frontend scripts separately."
