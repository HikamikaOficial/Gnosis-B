param($ResultsFile,$Worktree,$ToolRoot,$OpProfile)
$ErrorActionPreference = "Continue"
try { Set-Content -LiteralPath $ResultsFile -Value ("STARTED-TC user=" + (& C:\Windows\System32\whoami.exe)) -ErrorAction Stop } catch {}
function Emit($m){ try { Add-Content -LiteralPath $ResultsFile -Value ([string]$m) } catch {} }

$py   = "$ToolRoot\python\python.exe"
$claude = "$ToolRoot\claudebin\claude.exe"
$codexps = "$ToolRoot\codex\codex.ps1"
$git  = "C:\Program Files\Git\cmd\git.exe"
$node = "C:\Program Files\nodejs\node.exe"

function RunTimed($label,$exe,$argv,$ms){
  $o="$Worktree\o.txt"; $e="$Worktree\e.txt"
  try {
    $sw=[System.Diagnostics.Stopwatch]::StartNew()
    $p=Start-Process -FilePath $exe -ArgumentList $argv -NoNewWindow -PassThru -RedirectStandardOutput $o -RedirectStandardError $e -ErrorAction Stop
    if($p.WaitForExit($ms)){ $sw.Stop()
      $out=(((Get-Content $o -ErrorAction SilentlyContinue) + (Get-Content $e -ErrorAction SilentlyContinue)) -join ' ')
      if($out.Length -gt 120){ $out=$out.Substring(0,120) }
      Emit "$label = exit=$($p.ExitCode) $([math]::Round($sw.Elapsed.TotalMilliseconds))ms : $($out -replace '\s+',' ')"
    } else { try{$p.Kill()}catch{}; Emit "$label = TIMEOUT >${ms}ms (killed; possible network/hang)" }
  } catch { Emit "$label = LAUNCH-FAIL $($_.Exception.GetType().Name): $($_.Exception.Message)" }
}
function TryWrite($label,$path){ try { Set-Content -LiteralPath $path -Value "x" -ErrorAction Stop; Emit "$label = WRITABLE (BAD)" } catch { Emit "$label = WRITE-DENIED ($($_.Exception.GetType().Name))" } }

Emit "== TOOLCHAIN ACL (worker: execute yes, write no) =="
TryWrite "python_exe_write"  $py
TryWrite "claude_exe_write"  $claude
TryWrite "codex_ps1_write"   $codexps
TryWrite "gnosis_mod_write"  "$ToolRoot\gnosis\kernel\authority.py"
TryWrite "node_exe_write"    $node

Emit "== PYTHON (relocated, RX-only) =="
RunTimed "python_version" $py @("--version") 15000
$scr="$Worktree\s.py"; Set-Content $scr "import sys,json,os,subprocess; print('IMPORTS_OK', sys.version[:6])"
RunTimed "python_script_stdlib" $py @($scr) 15000
$imp="$Worktree\imp.py"; Set-Content $imp "import sys; sys.path.insert(0, r'$ToolRoot'); import gnosis.kernel.canonical as c; print('GNOSIS_IMPORT_OK', c.GENESIS_HASH[:6])"
RunTimed "python_import_gnosis" $py @($imp) 20000
# minimal pytest (trivial test) from the relocated python, writing pyc only where allowed
$td="$Worktree\t"; New-Item -ItemType Directory $td -Force | Out-Null
Set-Content "$td\test_x.py" "def test_ok():`n    assert 1+1==2"
RunTimed "python_pytest_minimal" $py @("-m","pytest","$td","-q") 40000
Emit "pycache_in_toolchain_after = $([bool](Get-ChildItem "$ToolRoot\python" -Recurse -Filter '__pycache__' -ErrorAction SilentlyContinue | Where-Object { Test-Path (Join-Path $_.FullName '*.pyc') }))"

Emit "== NODE (shared Program Files) =="
RunTimed "node_version" $node @("--version") 15000

Emit "== GIT (shared) =="
$dg="$Worktree\repo"; New-Item -ItemType Directory $dg -Force | Out-Null
& $git -C $dg init -q 2>&1 | Out-Null; & $git -C $dg config user.email a@b.c 2>&1 | Out-Null; & $git -C $dg config user.name w 2>&1 | Out-Null
Set-Content "$dg\a.txt" "x"; & $git -C $dg add -A 2>&1 | Out-Null; & $git -C $dg commit -m p 2>&1 | Out-Null
Emit "git_commit = $(if($LASTEXITCODE -eq 0){'PASS ' + (& $git -C $dg rev-parse --short HEAD 2>&1)}else{'FAIL'})"

Emit "== CLAUDE (relocated; startup only, no login) =="
RunTimed "claude_version" $claude @("--version") 20000

Emit "== CODEX (relocated + shared node; startup only, no login) =="
RunTimed "codex_version" "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" @("-NoProfile","-ExecutionPolicy","Bypass","-File",$codexps,"--version") 30000

Emit "== IMPORT POISONING (worker plants a shadow module in its worktree CWD) =="
Set-Content "$Worktree\evilmod.py" "print('POISONED')"
$imp2="$Worktree\imp2.py"; Set-Content $imp2 "import sys; sys.path.insert(0, r'$ToolRoot'); import gnosis.kernel.canonical; print('TRUSTED_IMPORT_STILL_CLEAN')"
# run with CWD=worktree (where evilmod lives) but trusted code from ToolRoot on path first
RunTimed "python_import_with_worker_cwd" $py @($imp2) 20000
Emit "note: worker CWD/worktree is deliberately worker-writable (it runs untrusted code there); trust-plane import path is ToolRoot (RX-only, worker cannot write)."

Emit "== CREDENTIAL ISOLATION (operator profile; ACCESSIBLE/NOT) =="
foreach($p in @("$OpProfile\.claude","$OpProfile\.codex","$OpProfile\.ssh")){
  $acc=$false; try { if(Test-Path $p){ $null=Get-ChildItem $p -Force -ErrorAction Stop; $acc=$true } else { Emit "$p = ABSENT-from-worker"; continue } } catch { $acc=$false }
  Emit "$p = $(if($acc){'ACCESSIBLE'}else{'NOT ACCESSIBLE'})"
}
Emit "== DONE-TC =="
