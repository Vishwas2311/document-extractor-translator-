$ErrorActionPreference = "Stop"
$BackendScript = Join-Path $PSScriptRoot "start-backend.ps1"
$FrontendScript = Join-Path $PSScriptRoot "start-frontend.ps1"

Start-Process powershell.exe -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-File", $BackendScript
)
Start-Sleep -Seconds 2
Start-Process powershell.exe -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-File", $FrontendScript
)

Write-Host "CareTranslate Studio is starting:" -ForegroundColor Green
Write-Host "Frontend: http://localhost:3000"
Write-Host "API docs: http://localhost:8000/docs"
