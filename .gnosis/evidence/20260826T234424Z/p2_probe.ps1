# F-17 P2 SERVICE-SID PUBLISHER PROBE — full reversible orchestrator.
# Provision -> RESTRICTED virtual-account service -> worker attacks (as a distinct
# SID) -> squatting + crash consistency -> rollback + POST-FLIGHT. Everything is
# disposable; teardown runs in finally.
$ErrorActionPreference = "Continue"
$SP      = "C:\Users\nicol\AppData\Local\Temp\claude\C--Users-nicol-Desktop-Claude-Code-Proyectos-GnosisAgentAi\6ff48a69-99d0-47f4-96c7-ff4ce9d8b55d\scratchpad\p2"
$svc="GnosisTrustedPublisherProbe"; $account="NT SERVICE\$svc"; $user="GnosisP2Worker"
$pf="C:\Program Files\Gnosis\TrustProbe"; $pd="C:\ProgramData\Gnosis\TrustProbe"; $work="C:\ProgramData\Gnosis\P2Work"
$srcRt="C:\Users\nicol\AppData\Roaming\uv\python\cpython-3.12-windows-x86_64-none"
$srcPub="$SP\publisher"
$venv="C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi\.venv\Scripts\python.exe"
$sc="$env:SystemRoot\System32\sc.exe"; $icacls="$env:SystemRoot\System32\icacls.exe"; $robo="$env:SystemRoot\System32\robocopy.exe"
$pipeShort="GnosisTrustedPublisherProbe"; $pipeFull="\\.\pipe\$pipeShort"
$results="$work\attack-results.txt"
$out = New-Object System.Collections.ArrayList
function O($m){ [void]$out.Add([string]$m); Write-Output $m }

Add-Type @"
using System; using System.Runtime.InteropServices;
public class TL {
  [StructLayout(LayoutKind.Sequential)] public struct SI { public int cb; public string r1,desktop,title; public int x,y,xs,ys,xc,yc,fill,flags; public short show,r2; public IntPtr r3,hIn,hOut,hErr; }
  [StructLayout(LayoutKind.Sequential)] public struct PI { public IntPtr hProcess,hThread; public int pid,tid; }
  [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
  static extern bool CreateProcessWithLogonW(string u,string d,IntPtr pw,uint lf,string app,string cmd,uint cf,IntPtr env,string cd,ref SI si,out PI pi);
  [DllImport("kernel32.dll")] static extern uint WaitForSingleObject(IntPtr h,uint ms);
  [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
  public static int RunAs(string user,string domain,IntPtr pw,string cmd,string cd){
    var si=new SI(); si.cb=Marshal.SizeOf(si); PI pi;
    if(!CreateProcessWithLogonW(user,domain,pw,1u,null,cmd,0x400u,IntPtr.Zero,cd,ref si,out pi)) return -Marshal.GetLastWin32Error();
    WaitForSingleObject(pi.hProcess,120000); CloseHandle(pi.hProcess); CloseHandle(pi.hThread); return 0;
  }
  public static int RunAsNoWait(string user,string domain,IntPtr pw,string cmd,string cd){
    var si=new SI(); si.cb=Marshal.SizeOf(si); PI pi;
    if(!CreateProcessWithLogonW(user,domain,pw,1u,null,cmd,0x400u,IntPtr.Zero,cd,ref si,out pi)) return -Marshal.GetLastWin32Error();
    CloseHandle(pi.hProcess); CloseHandle(pi.hThread); return pi.pid;
  }
}
"@

function Svc-State { (& $sc query $svc 2>$null | Select-String "RUNNING|STOPPED|START_PENDING|STOP_PENDING") -replace '.*:\s*','' -replace '\s+.*','' }
function Start-Svc { & $sc start $svc *> $null; for($i=0;$i -lt 25;$i++){ Start-Sleep -Milliseconds 400; if((& $sc query $svc)-match "RUNNING"){return "RUNNING"}; if((& $sc query $svc)-match "STOPPED"){return "STOPPED"} }; return "?" }
function Stop-Svc { & $sc stop $svc *> $null; for($i=0;$i -lt 20;$i++){ Start-Sleep -Milliseconds 300; if((& $sc query $svc)-match "STOPPED"){break} }; Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*TrustProbe*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } }

try {
  # ---------------- PRE-FLIGHT ----------------
  O "===== PRE-FLIGHT ====="
  O ("HEAD = " + (& git -C 'C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi' rev-parse --short HEAD))
  O ("git_status = " + ((& git -C 'C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi' status --porcelain) -join '|'))
  O ("pre_gnosis_svcs  = " + (((Get-Service -Name '*Gnosis*' -ErrorAction SilentlyContinue).Name) -join ','))
  O ("pre_gnosis_users = " + (((Get-LocalUser -Name 'Gnosis*' -ErrorAction SilentlyContinue).Name) -join ','))
  O ("pre_gnosis_tasks = " + (((Get-ScheduledTask -TaskName '*Gnosis*' -ErrorAction SilentlyContinue).TaskName) -join ','))
  O ("pre_pf=" + (Test-Path $pf) + " pre_pd=" + (Test-Path $pd) + " pre_work=" + (Test-Path $work))
  O ("pre_pipe = " + [bool]([System.IO.Directory]::GetFiles('\\.\pipe\') | Where-Object { $_ -like "*$pipeShort*" }))

  $svcSid=((& $sc showsid $svc | Select-String "SERVICE SID:|SID DE SERVICIO:") -replace '.*:\s*','').Trim()
  O "svc_sid = $svcSid"

  # ---------------- PROVISION ----------------
  O "===== PROVISION ====="
  New-Item -ItemType Directory -Force "$pf\runtime","$pf\publisher","$pd\anchors","$pd\runidentity","$pd\bundles","$work" | Out-Null
  & $robo $srcRt "$pf\runtime" /E /NFL /NDL /NJH /NJS /NP *> $null
  & $robo $srcPub "$pf\publisher" /E /NFL /NDL /NJH /NJS /NP *> $null

  # worker user (disposable, non-admin)
  $secure = New-Object System.Security.SecureString
  foreach($c in "Aa1!".ToCharArray()){ $secure.AppendChar($c) }
  $rb = New-Object 'byte[]' 24; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($rb)
  foreach($b in $rb){ $secure.AppendChar([char](65 + ($b % 26))) }
  $secure.MakeReadOnly(); [Array]::Clear($rb,0,$rb.Length)
  New-LocalUser -Name $user -Password $secure -FullName "F17 P2 worker probe" -Description "delete after" -AccountNeverExpires -UserMayNotChangePassword | Out-Null
  Add-LocalGroupMember -Group "Usuarios" -Member $user -ErrorAction SilentlyContinue
  $workerSid=(Get-LocalUser $user).SID.Value
  O "worker_sid = $workerSid  admin=$([bool]((Get-LocalGroupMember 'Administradores' -ErrorAction SilentlyContinue).Name -contains ""$env:COMPUTERNAME\$user""))"

  # bundle (self-consistent) built ENTIRELY by python so SUMMARY.json has NO BOM
  # (authority._bundle_head_sha reads it as plain utf-8; a PowerShell BOM breaks it).
  $bundle="$pd\bundles\bundle_A"; New-Item -ItemType Directory -Force $bundle | Out-Null
  $head = "a"*40
  $mkbundle = @"
import sys, json
sys.path.insert(0, r'$srcPub')
from pathlib import Path
from trust.bundle_verify import write_bundle_manifest
b = Path(r'$bundle'); b.mkdir(parents=True, exist_ok=True)
(b/'SUMMARY.json').write_text(json.dumps({'tree_identity':{'post':{'fingerprint':{'head_sha':'$head'}}},'boundary':{'protection':{'content_digest':'deadbeef'}}}), encoding='utf-8')
(b/'artifact.txt').write_text('evidence payload', encoding='utf-8')
write_bundle_manifest(b)
print('bundle ok (no BOM)')
"@
  $mkbundle | & $venv -

  # trusted RunIdentity records (owner run_A = worker; run_B = other SID)
  @{ task_id="t1"; run_id="run_A"; repository_id="repoX"; head_sha=$head; bundle_path=$bundle; owner_worker_sid=$workerSid } | ConvertTo-Json | Set-Content -Encoding UTF8 "$pd\runidentity\run_A.json"
  @{ task_id="t2"; run_id="run_B"; repository_id="repoX"; head_sha=$head; bundle_path=$bundle; owner_worker_sid="S-1-5-21-0-0-0-9999" } | ConvertTo-Json | Set-Content -Encoding UTF8 "$pd\runidentity\run_B.json"

  # config (authorized worker + pipe SDDL: worker minimal, NO create-instance bit)
  $pipeSddl = "D:(A;;FA;;;$svcSid)(A;;FA;;;SY)(A;;FA;;;BA)(A;;0x0012019B;;;$workerSid)"
  @{ trust_state_root=$pd; pipe_name=$pipeFull; pipe_sddl=$pipeSddl; authorized_worker_sid=$workerSid; service_name=$svc } | ConvertTo-Json | Set-Content -Encoding UTF8 "$pd\config.json"

  # ACLs: trust code RX for svc; state F for svc; BOTH deny worker (no ACE). work dir = worker RW.
  & $icacls $pf /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" ("*${svcSid}:(OI)(CI)RX") /q *> $null
  & $icacls "$pf\*" /reset /t /q *> $null
  & $icacls $pd /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" ("*${svcSid}:(OI)(CI)F") /q *> $null
  & $icacls "$pd\*" /reset /t /q *> $null
  & $icacls $work /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" ("*${workerSid}:(OI)(CI)M") /q *> $null
  Copy-Item "$SP\worker_attacks.ps1" "$work\worker_attacks.ps1" -Force
  Copy-Item "$SP\squat.ps1" "$work\squat.ps1" -Force
  O ("python.exe effective ACL: " + ((& $icacls "$pf\runtime\python.exe") -join ' '))
  O ("anchorstore dir ACL: " + ((& $icacls "$pd\anchors") -join ' '))

  # ---------------- SERVICE (RESTRICTED, hardened object DACL) ----------------
  O "===== SERVICE ====="
  $binpath="`"$pf\runtime\python.exe`" -I -S `"$pf\publisher\main.py`" service `"$pd\config.json`""
  New-Service -Name $svc -BinaryPathName $binpath -StartupType Manual -ErrorAction SilentlyContinue | Out-Null
  & $sc config $svc obj= $account *> $null
  & $sc sidtype $svc restricted | Out-Null
  & $sc privs $svc SeChangeNotifyPrivilege | Out-Null
  # service object DACL: SYSTEM + Admins full; worker NO ACE
  $svcSddl = "D:(A;;CCLCSWRPWPDTLOCRSDRCWDWO;;;SY)(A;;CCLCSWRPWPDTLOCRSDRCWDWO;;;BA)S:(AU;FA;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;WD)"
  & $sc sdset $svc $svcSddl *> $null
  O ("service sidtype: " + ((& $sc qsidtype $svc | Select-String 'SERVICE') -replace '\s+',' '))
  O ("service privs:   " + ((& $sc qprivs $svc | Select-String 'Se') -replace '\s+',' '))
  O ("service SDDL:     " + ((& $sc sdshow $svc) -join ''))
  $st = Start-Svc
  O "service_state = $st"
  Start-Sleep -Milliseconds 700
  $pubPid = [int]((Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*TrustProbe*" } | Select-Object -First 1).ProcessId)
  O "publisher_pid = $pubPid"
  if (Test-Path "$pd\token-dump.json") { O ("TOKEN: " + ((Get-Content "$pd\token-dump.json" -Raw) -replace '\s+',' ')) }

  # ---------------- WORKER ATTACKS (as distinct SID) ----------------
  O "===== WORKER ATTACKS ====="
  if (Test-Path $results) { Remove-Item $results -Force }
  $cmd = "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$work\worker_attacks.ps1`" -ResultsFile `"$results`" -PipeShort `"$pipeShort`" -Svc `"$svc`" -Pf `"$pf`" -Pd `"$pd`" -PubPid $pubPid -WorkDir `"$work`""
  $pwPtr = [System.Runtime.InteropServices.Marshal]::SecureStringToGlobalAllocUnicode($secure)
  try { $rc=[TL]::RunAs($user,".",$pwPtr,$cmd,$work); O "worker launch rc=$rc" } finally { [System.Runtime.InteropServices.Marshal]::ZeroFreeGlobalAllocUnicode($pwPtr) }
  Start-Sleep -Milliseconds 1200
  if (Test-Path $results) { Get-Content $results | ForEach-Object { O ("  " + $_) } } else { O "NO ATTACK RESULTS" }
  O ("ledger_records = " + $(if (Test-Path "$pd\anchors\anchors.jsonl") { (Get-Content "$pd\anchors\anchors.jsonl").Count } else { 0 }))
  O ("watermark = " + $(if (Test-Path "$pd\anchors\committed.seq") { Get-Content "$pd\anchors\committed.seq" } else { 'none' }))

  # ---------------- PIPE SQUATTING (worker pre-creates the pipe) ----------------
  O "===== PIPE SQUATTING ====="
  Stop-Svc
  if (Test-Path "$work\squat.txt") { Remove-Item "$work\squat.txt" -Force }
  if (Test-Path "$pd\publisher.log") { Remove-Item "$pd\publisher.log" -Force }
  # worker holds the pipe open (non-blocking launch) while the service tries to start
  $squat = "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$work\squat.ps1`" -PipeShort `"$pipeShort`" -Marker `"$work\squat.txt`""
  $pwPtr2 = [System.Runtime.InteropServices.Marshal]::SecureStringToGlobalAllocUnicode($secure)
  try { [void][TL]::RunAsNoWait($user,".",$pwPtr2,$squat,$work) } finally { [System.Runtime.InteropServices.Marshal]::ZeroFreeGlobalAllocUnicode($pwPtr2) }
  Start-Sleep -Milliseconds 1800   # let the squatter create + hold the pipe
  O ("squat_marker = " + $(if (Test-Path "$work\squat.txt") { (Get-Content "$work\squat.txt" -Raw).Trim() } else { 'none' }))
  $st2 = Start-Svc
  O "service_state_with_squatter = $st2"
  Start-Sleep -Milliseconds 600
  O ("squat_publisher_log = " + $(if (Test-Path "$pd\publisher.log") { (((Get-Content "$pd\publisher.log" -Raw) -split "`n" | Where-Object { $_ -like '*FIRST_INSTANCE*' -or $_ -like '*workload*' }) | Select-Object -Last 1) } else { 'none' }))
  Stop-Svc
  Start-Sleep -Seconds 10   # wait out the squatter's hold so it releases the pipe
  Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*NamedPipeServerStream*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

  # ---------------- CRASH CONSISTENCY (watermark recovery) ----------------
  O "===== CRASH CONSISTENCY ====="
  # simulate a crash AFTER append but BEFORE watermark confirm: inject an extra
  # unconfirmed ledger line beyond the watermark, then restart -> recovery truncates it.
  $ledger = "$pd\anchors\anchors.jsonl"
  $before = $(if (Test-Path $ledger) { (Get-Content $ledger).Count } else { 0 })
  $wm = $(if (Test-Path "$pd\anchors\committed.seq") { Get-Content "$pd\anchors\committed.seq" } else { '-1' })
  Add-Content -LiteralPath $ledger -Value '{"schema":"x","task_id":"t","run_id":"crashy","repository_id":"r","head_sha":"a","tree_identity":"z","bundle_path":"b","bundle_digest":"deadbeef","seq":99,"prev_record_digest":"nope"}'
  O "injected_unconfirmed_line (seq=99 beyond watermark=$wm); ledger now $((Get-Content $ledger).Count) lines"
  $st3 = Start-Svc
  Start-Sleep -Milliseconds 700
  O "service_state_after_crash_restart = $st3"
  O ("recovery_log = " + $(if (Test-Path "$pd\publisher.log") { (((Get-Content "$pd\publisher.log" -Raw) -split "`n" | Where-Object { $_ -like '*recovery*' }) | Select-Object -Last 1) } else { 'none' }))
  O ("ledger_after_recovery = " + (Get-Content $ledger).Count + " (before crash-inject = $before)")
  Stop-Svc
}
finally {
  # ---------------- ROLLBACK ----------------
  O "===== ROLLBACK ====="
  Stop-Svc
  & $sc delete $svc *> $null; Start-Sleep -Milliseconds 500
  Get-CimInstance Win32_UserProfile -ErrorAction SilentlyContinue | Where-Object { $_.LocalPath -like "*\$user" } | ForEach-Object { try { Remove-CimInstance $_ -ErrorAction Stop } catch {} }
  try { Remove-LocalUser -Name $user -ErrorAction Stop } catch {}
  foreach ($p in @($pf,$pd,$work)) {
    if (Test-Path $p) {
      & "$env:SystemRoot\System32\takeown.exe" /f $p /r /a /d S *> $null
      & $icacls $p /reset /t /q *> $null
      Get-ChildItem $p -Recurse -Force -ErrorAction SilentlyContinue | ForEach-Object { try { $_.Attributes='Normal' } catch {} }
      Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue
      if (Test-Path $p) { try { [System.IO.Directory]::Delete($p,$true) } catch {} }
    }
  }
  foreach ($parent in @("C:\Program Files\Gnosis","C:\ProgramData\Gnosis")) {
    if ((Test-Path $parent) -and -not (Get-ChildItem $parent -Force -ErrorAction SilentlyContinue)) { Remove-Item -LiteralPath $parent -Force -ErrorAction SilentlyContinue }
  }
  # ---------------- POST-FLIGHT ----------------
  O "===== POST-FLIGHT ====="
  O ("post_svc_present  = " + (((& $sc query $svc 2>$null | Select-String 'SERVICE_NAME') -ne $null)))
  O ("post_user_present = " + ([bool](Get-LocalUser -Name $user -ErrorAction SilentlyContinue)))
  O ("post_profile_left = " + ([bool](Get-CimInstance Win32_UserProfile -ErrorAction SilentlyContinue | Where-Object { $_.LocalPath -like "*\$user" })))
  O ("post_pf=" + (Test-Path $pf) + " post_pd=" + (Test-Path $pd) + " post_work=" + (Test-Path $work))
  O ("post_pipe = " + [bool]([System.IO.Directory]::GetFiles('\\.\pipe\') | Where-Object { $_ -like "*$pipeShort*" }))
  O ("post_gnosis_svcs  = " + (((Get-Service -Name '*Gnosis*' -ErrorAction SilentlyContinue).Name) -join ','))
  O ("post_gnosis_users = " + (((Get-LocalUser -Name 'Gnosis*' -ErrorAction SilentlyContinue).Name) -join ','))
  O ("post_gnosis_tasks = " + (((Get-ScheduledTask -TaskName '*Gnosis*' -ErrorAction SilentlyContinue).TaskName) -join ','))
  O ("post_HEAD = " + (& git -C 'C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi' rev-parse --short HEAD))
  Set-Content -Path "$SP\PROBE-RESULTS.txt" -Value ($out -join "`r`n") -Encoding UTF8
  O "results -> $SP\PROBE-RESULTS.txt"
}
