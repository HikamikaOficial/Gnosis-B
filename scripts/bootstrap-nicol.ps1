$ErrorActionPreference = "Stop"

$ExpectedRoot = "C:\\Users\\nicol\\Desktop\\Claude Code Proyectos\\GnosisAgentAi"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

Write-Host "GNOSIS bootstrap for Nicol"
Write-Host "Actual root: $Root"
Write-Host "Expected root: C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi"

$dirs = @(
  "external\repositories",
  ".gnosis\state", ".gnosis\runtime", ".gnosis\logs", ".gnosis\traces",
  ".gnosis\artifacts", ".gnosis\workspaces", ".gnosis\tmp",
  "docs\research", "docs\adr",
  "memory\adapters", "memory\obsidian-vault",
  "lab\learning\candidates", "lab\learning\promoted",
  "lab\training\datasets", "lab\training\experiments", "lab\training\models",
  "benchmarks", "experiments"
)
foreach ($d in $dirs) {
  New-Item -ItemType Directory -Force -Path (Join-Path $Root $d) | Out-Null
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Write-Warning "Git not found. Install Git for Windows before autonomous development."
} elseif (-not (Test-Path ".git")) {
  git init | Out-Null
  try { git branch -M main | Out-Null } catch {}
}

# Prefer py launcher, then python.
$Py = $null
if (Get-Command py -ErrorAction SilentlyContinue) { $Py = "py" }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $Py = "python" }

if ($Py) {
  & $Py .\scripts\inventory_repositories.py --root "C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi\external\repositories"
  & $Py .\scripts\doctor.py
  & $Py .\scripts\memory_doctor.py
} else {
  Write-Warning "Python not found. Claude should install Python 3.12+ or uv, then rerun bootstrap."
}

Write-Host ""
Write-Host "Bootstrap complete."
Write-Host "Next: run .\scripts\launch-gnosis-claude.ps1"
