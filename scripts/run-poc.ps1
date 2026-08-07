$ErrorActionPreference = "Stop"
Write-Warning "run-poc.ps1 is retained as a compatibility shim. Use run-local.ps1."
& (Join-Path $PSScriptRoot "run-local.ps1")
