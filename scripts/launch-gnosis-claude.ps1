$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
  throw "Claude Code is not installed or not on PATH."
}

# Fable 5 + Ultracode for the primary build session.
# Auto mode is used when the installed Claude Code/account supports it.
$args = @("--model", "fable", "--effort", "ultracode", "--permission-mode", "auto")

Write-Host "Starting Claude Code for GNOSIS..."
Write-Host "Root: $Root"
Write-Host "Model: Fable 5"
Write-Host "Effort: Ultracode"
Write-Host "Permission mode: Auto"
Write-Host ""
Write-Host "First instruction:"
Write-Host "Read 01_START_HERE.md and execute it completely."

& claude @args
