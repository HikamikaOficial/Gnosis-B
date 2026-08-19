$ErrorActionPreference = "Continue"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
$Out = "docs\research\ENVIRONMENT_AUDIT_AUTOMATED.md"

"# Automated Environment Audit`r`n" | Set-Content $Out
"Generated: $(Get-Date -Format o)`r`n" | Add-Content $Out
"Root: $Root`r`n" | Add-Content $Out

$commands = @("git","python","uv","claude","codex","docker","wsl","node","npm")
foreach ($c in $commands) {
  $cmd = Get-Command $c -ErrorAction SilentlyContinue
  if ($cmd) {
    $v = try { & $c --version 2>&1 | Select-Object -First 1 } catch { "installed" }
    "- ${c}: $v" | Add-Content $Out
  } else {
    "- ${c}: NOT FOUND" | Add-Content $Out
  }
}

"`r`n## Git`r`n" | Add-Content $Out
git status --short --branch 2>&1 | Add-Content $Out
git rev-parse --show-toplevel 2>&1 | Add-Content $Out

"`r`n## External repository count`r`n" | Add-Content $Out
if (Test-Path "external\repositories") {
  $count = (Get-ChildItem "external\repositories" -Directory -Recurse -Force | Where-Object { Test-Path (Join-Path $_.FullName ".git") }).Count
  "- Git repositories discovered: $count" | Add-Content $Out
}
Write-Host "Wrote $Out"
