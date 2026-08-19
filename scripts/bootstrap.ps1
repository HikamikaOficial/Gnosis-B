$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$Report = @()
$Report += "# GNOSIS Bootstrap Report"
$Report += ""
$Report += "**Generated:** $(Get-Date -Format o)"
$Report += "**Root:** `$Root`"
$Report += ""

function Check-Cmd($name) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) {
        try { $ver = & $name --version 2>&1 | Select-Object -First 1 } catch { $ver = "installed" }
        $script:Report += "- [x] $name — $ver"
        return $true
    } else {
        $script:Report += "- [ ] $name — NOT FOUND"
        return $false
    }
}

$dirs = @(
  ".gnosis\runtime", ".gnosis\workspaces", ".gnosis\logs", ".gnosis\traces",
  ".gnosis\artifacts", ".gnosis\state", "docs\adr", "docs\research",
  "lab\learning\candidates", "lab\learning\promoted", "lab\training\datasets",
  "lab\training\experiments", "lab\training\models", "benchmarks", "experiments",
  "src\gnosis", "tests\unit", "tests\integration", "tests\recovery",
  "tests\security", "tests\chaos"
)
foreach ($d in $dirs) { New-Item -ItemType Directory -Force -Path (Join-Path $Root $d) | Out-Null }

$hasGit = Check-Cmd "git"
if ($hasGit -and -not (Test-Path ".git")) {
    git init | Out-Null
    try { git branch -M main | Out-Null } catch {}
    $Report += ""
    $Report += "- Initialized local Git repository."
} elseif (-not $hasGit) {
    $Report += "- [!] Git is required before repository initialization."
}

$hasPython = Check-Cmd "python"
$hasClaude = Check-Cmd "claude"
$hasCodex = Check-Cmd "codex"
$hasUv = Check-Cmd "uv"
$hasDocker = Check-Cmd "docker"
$hasWsl = Check-Cmd "wsl"

if ($hasPython) {
    $Py = (Get-Command python).Source.Replace("\", "\\")
    $Settings = @{
      hooks = @{
        PreToolUse = @(
          @{
            matcher = "Bash|PowerShell|Read|Edit|Write"
            hooks = @(
              @{ type = "command"; command = "`"$((Get-Command python).Source)`" `"$Root\.claude\hooks\policy_gate.py`""; timeout = 10 }
            )
          }
        )
        PostToolUse = @(
          @{
            matcher = "Bash|PowerShell|Read|Edit|Write"
            hooks = @(
              @{ type = "command"; command = "`"$((Get-Command python).Source)`" `"$Root\.claude\hooks\audit_event.py`""; timeout = 10 }
            )
          }
        )
        SessionStart = @(
          @{
            hooks = @(
              @{ type = "command"; command = "`"$((Get-Command python).Source)`" `"$Root\.claude\hooks\session_context.py`""; timeout = 10 }
            )
          }
        )
      }
    }
    $Settings | ConvertTo-Json -Depth 12 | Set-Content -Encoding UTF8 ".claude\settings.local.json"
    $Report += "- [x] Local deterministic hooks configured."
} else {
    $Report += "- [!] Hooks not enabled because Python was not found. Claude must install/configure Python before enabling them."
}

if ($hasPython -and -not (Test-Path ".venv")) {
    try {
        python -m venv .venv
        $Report += "- [x] Created .venv."
    } catch {
        $Report += "- [!] Could not create .venv: $($_.Exception.Message)"
    }
}

$Report += ""
$Report += "## Next"
$Report += ""
$Report += "1. Start Claude Code in this root."
$Report += "2. Read `01_START_HERE.md`."
$Report += "3. Claude must audit missing tools and install only justified dependencies using official sources."
$Report += "4. Place external repositories under `external/repositories/`."

$Report -join "`r`n" | Set-Content -Encoding UTF8 "docs\research\BOOTSTRAP_REPORT.md"
Write-Host "GNOSIS bootstrap complete. See docs/research/BOOTSTRAP_REPORT.md"
