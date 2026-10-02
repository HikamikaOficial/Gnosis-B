param($ResultsFile,$DirectorPid,$Worktree,$Anchor,$Tcb,$RunId,$ToolCopy,$OpProfile)
$ErrorActionPreference = "Continue"
$r = New-Object System.Collections.ArrayList
try { Set-Content -LiteralPath $ResultsFile -Value ("STARTED user=" + (& C:\Windows\System32\whoami.exe) + " cwd=" + (Get-Location).Path) -ErrorAction Stop } catch {}
function Emit($m){ [void]$r.Add([string]$m); try { Add-Content -LiteralPath $ResultsFile -Value ([string]$m) } catch {} }
try {
  Emit "== IDENTITY =="
  Emit ((&whoami /all 2>&1 | Out-String))

  Emit "== ACL MATRIX (effective access, run as the worker) =="
  function TryFile($name,$block){ try { & $block; Emit "$name = ALLOWED" } catch { Emit "$name = DENIED ($($_.Exception.GetType().Name))" } }
  TryFile "worktree_write"  { Set-Content "$Worktree\w.txt" "x" -ErrorAction Stop }
  TryFile "worktree_create" { New-Item "$Worktree\new.txt" -ItemType File -Force -ErrorAction Stop | Out-Null }
  TryFile "worktree_delete" { Remove-Item "$Worktree\w.txt" -ErrorAction Stop }
  TryFile "tcb_read"        { Get-Content "$Tcb\trusted_mod.py" -ErrorAction Stop | Out-Null }
  TryFile "tcb_write"       { Set-Content "$Tcb\trusted_mod.py" "POISON" -ErrorAction Stop }
  TryFile "runid_read"      { Get-Content "$RunId\id.json" -ErrorAction Stop | Out-Null }
  TryFile "runid_write"     { Set-Content "$RunId\forged.json" "x" -ErrorAction Stop }
  TryFile "anchor_create"   { Set-Content "$Anchor\evil.txt" "x" -ErrorAction Stop }
  TryFile "anchor_delete"   { Remove-Item "$Anchor\seed.txt" -ErrorAction Stop }
  TryFile "anchor_rename"   { Rename-Item "$Anchor\seed.txt" "$Anchor\seed2.txt" -ErrorAction Stop }
  function IcaclsProbe($name,$a){ $null = & "$env:SystemRoot\System32\icacls.exe" $Anchor @a 2>&1; Emit "$name = $(if($LASTEXITCODE -eq 0){'ALLOWED'}else{'DENIED'})" }
  IcaclsProbe "anchor_change_dacl"  @("/grant","*S-1-1-0:(F)","/q")
  IcaclsProbe "anchor_take_owner"   @("/setowner",$env:USERNAME,"/q")
  IcaclsProbe "anchor_lower_label"  @("/setintegritylevel","Medium","/q")

  Emit "== CROSS-PROCESS (worker to High Director pid $DirectorPid) =="
  Add-Type @"
using System; using System.Runtime.InteropServices;
public class XP {
  [DllImport("kernel32.dll", SetLastError=true)] public static extern IntPtr OpenProcess(uint a, bool inh, uint pid);
  [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);
}
"@
  $rights = @{ "PROCESS_DUP_HANDLE"=0x0040; "PROCESS_VM_WRITE"=0x0020; "PROCESS_VM_OPERATION"=0x0008; "PROCESS_CREATE_THREAD"=0x0002; "PROCESS_CREATE_PROCESS"=0x0080 }
  foreach($k in $rights.Keys){
    $h = [XP]::OpenProcess([uint32]$rights[$k], $false, [uint32]$DirectorPid)
    if($h -ne [IntPtr]::Zero){ Emit "OpenProcess($k) = SUCCEEDED"; [void][XP]::CloseHandle($h) }
    else { Emit "OpenProcess($k) = DENIED err=$([Runtime.InteropServices.Marshal]::GetLastWin32Error())" }
  }

  Emit "== CREDENTIAL ISOLATION (ACCESSIBLE or NOT ACCESSIBLE, no values) =="
  foreach($p in @("$OpProfile\.claude","$OpProfile\.codex","$OpProfile\.gitconfig","$OpProfile\.ssh")){
    if(-not (Test-Path $p)){ Emit "$p = ABSENT"; continue }
    $acc=$false
    try { $it=Get-Item $p -Force -ErrorAction Stop; if($it -is [System.IO.DirectoryInfo]){ $null=Get-ChildItem $p -Force -ErrorAction Stop } else { $null=Get-Content $p -TotalCount 1 -ErrorAction Stop }; $acc=$true } catch { $acc=$false }
    Emit "$p = $(if($acc){'ACCESSIBLE'}else{'NOT ACCESSIBLE'})"
  }

  Emit "== GIT (Program Files, shared) =="
  $dg = Join-Path $Worktree "disposable_repo"; New-Item $dg -ItemType Directory -Force | Out-Null
  $git = "C:\Program Files\Git\cmd\git.exe"
  try {
    & $git -C $dg init -q 2>&1 | Out-Null
    & $git -C $dg config user.email "wkr@probe.local" 2>&1 | Out-Null
    & $git -C $dg config user.name "worker" 2>&1 | Out-Null
    Set-Content "$dg\a.txt" "hello"
    & $git -C $dg add -A 2>&1 | Out-Null
    & $git -C $dg commit -m probe 2>&1 | Out-Null
    $sha = (& $git -C $dg rev-parse --short HEAD 2>&1)
    Emit "git init/config/add/commit = PASS (commit $sha)"
  } catch { Emit "git = FAIL ($($_.Exception.Message))" }

  Emit "== PYTHON =="
  $venvpy = "C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi\.venv\Scripts\python.exe"
  $pycode = 'import sys; print("PYOK", sys.version[:6])'
  try { $o = (& $venvpy -c $pycode 2>&1 | Out-String); Emit "real venv python (operator profile) = $(if($o -match 'PYOK'){'ACCESSIBLE ('+($o.Trim())+')'}else{'NOT ACCESSIBLE'})" } catch { Emit "real venv python = NOT ACCESSIBLE ($($_.Exception.GetType().Name))" }
  $copypy = Join-Path $ToolCopy "python\python.exe"
  if(Test-Path $copypy){ try { $o=(& $copypy -c $pycode 2>&1 | Out-String); Emit "copied python = $(if($o -match 'PYOK'){'PASS'}else{'FAIL'})" } catch { Emit "copied python = FAIL" } } else { Emit "copied python = NOT TESTED (copy skipped for speed/reversibility)" }

  Emit "== CLAUDE / CODEX (startup only, no login, no provider call) =="
  $realclaude = "C:\Users\nicol\.local\bin\claude.exe"
  try { $o=(& $realclaude --version 2>&1 | Out-String); Emit "real claude (operator profile) = $(if($LASTEXITCODE -eq 0 -or $o.Trim()){'ACCESSIBLE'}else{'NOT ACCESSIBLE'})" } catch { Emit "real claude = NOT ACCESSIBLE ($($_.Exception.GetType().Name))" }
  Emit "codex = NOT TESTED (codex.ps1 under operator profile needs node/npm; copy impractical) - EXPECTED compat cost"
}
catch { Emit "WORKER FATAL: $($_.Exception.Message)" }
finally { try { Add-Content -LiteralPath $ResultsFile -Value "== DONE ==" } catch {} }
