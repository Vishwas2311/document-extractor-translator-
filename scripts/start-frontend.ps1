$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$FrontendRoot = Join-Path $ProjectRoot "frontend"

if (-not (Test-Path (Join-Path $FrontendRoot "node_modules"))) {
    throw "Frontend dependencies are missing. Run scripts\setup.ps1 first."
}
if (-not (Test-Path (Join-Path $FrontendRoot ".env.local"))) {
    Copy-Item (Join-Path $FrontendRoot ".env.local.example") (Join-Path $FrontendRoot ".env.local")
}

Set-Location $FrontendRoot
npm run dev
