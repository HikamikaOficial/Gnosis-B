$ErrorActionPreference = "Continue"
Add-Type @"
using System; using System.Runtime.InteropServices;
public class Launcher {
  [StructLayout(LayoutKind.Sequential)] public struct STARTUPINFO {
    public int cb; public string r1,desktop,title; public int x,y,xs,ys,xc,yc,fill,flags;
    public short show,r2; public IntPtr r3,hIn,hOut,hErr; }
  [StructLayout(LayoutKind.Sequential)] public struct PI { public IntPtr hProcess,hThread; public int pid,tid; }
  [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
  static extern bool CreateProcessWithLogonW(string u,string d,IntPtr pw,uint lf,string app,string cmd,uint cf,IntPtr env,string cd,ref STARTUPINFO si,out PI pi);
  [DllImport("kernel32.dll")] static extern uint WaitForSingleObject(IntPtr h,uint ms);
  [DllImport("kernel32.dll")] static extern bool GetExitCodeProcess(IntPtr h,out uint c);
  [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
  public static int RunAs(string user,string domain,IntPtr pw,string cmd,string cd){
    var si=new STARTUPINFO(); si.cb=Marshal.SizeOf(si); PI pi;
    if(!CreateProcessWithLogonW(user,domain,pw,1u,null,cmd,0x400u,IntPtr.Zero,cd,ref si,out pi))
      return -Marshal.GetLastWin32Error();
    WaitForSingleObject(pi.hProcess,180000); uint code; GetExitCodeProcess(pi.hProcess,out code);
    CloseHandle(pi.hProcess); CloseHandle(pi.hThread); return (int)code;
  }
}
"@
$SP    = "C:\Users\nicol\AppData\Local\Temp\claude\C--Users-nicol-Desktop-Claude-Code-Proyectos-GnosisAgentAi\6ff48a69-99d0-47f4-96c7-ff4ce9d8b55d\scratchpad"
$probe = "C:\ProgramData\GnosisWorkerProbe"
$user  = "GnosisWorkerProbe"
$OpProfile = "C:\Users\nicol"
$report = Join-Path $SP "PROBE-RESULTS.txt"
$rep = New-Object System.Collections.ArrayList
function O($m){ [void]$rep.Add([string]$m); Write-Output $m }

O "===== F-17 DEDICATED-WORKER FEASIBILITY PROBE ====="
O "PRE-FLIGHT: HEAD=$(& git -C "C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi" rev-parse --short HEAD)  users(Gnosis*)=$(((Get-LocalUser -Name 'Gnosis*').Name) -join ',')  services(*Gnosis*)=$(((Get-Service -Name '*Gnosis*' -ErrorAction SilentlyContinue).Name) -join ',')"

# disposable probe dirs
if(Test-Path $probe){ [System.IO.Directory]::Delete($probe,$true) }
$worktree=Join-Path $probe "worktree"; $anchor=Join-Path $probe "anchor"; $tcb=Join-Path $probe "tcb"
$runid=Join-Path $probe "runid"; $toolcopy=Join-Path $probe "toolcopy"; $scripts=Join-Path $probe "scripts"; $results=Join-Path $probe "results"
$worker=$false
try {
  # --- SecureString password: complexity seed + 20 crypto-random A-Z; never a plaintext string ---
  $secure = New-Object System.Security.SecureString
  foreach($c in "Aa1!".ToCharArray()){ $secure.AppendChar($c) }
  $rb = New-Object 'byte[]' 20; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($rb)
  foreach($b in $rb){ $secure.AppendChar([char](65 + ($b % 26))) }
  $secure.MakeReadOnly()
  [Array]::Clear($rb,0,$rb.Length)

  New-LocalUser -Name $user -Password $secure -FullName "F17 disposable probe" -Description "F-17 feasibility probe; delete after" -AccountNeverExpires -UserMayNotChangePassword | Out-Null
  $worker = $true
  Add-LocalGroupMember -Group "Usuarios" -Member $user -ErrorAction SilentlyContinue
  $sid = (Get-LocalUser $user).SID.Value
  O "created NON-admin user $user  SID=$sid  groups=$(((Get-LocalGroup | Where-Object { (Get-LocalGroupMember $_.Name -ErrorAction SilentlyContinue).Name -contains ""$env:COMPUTERNAME\$user"" }).Name) -join ',')"
  O "is in Administradores: $([bool]((Get-LocalGroupMember 'Administradores' -ErrorAction SilentlyContinue).Name -contains ""$env:COMPUTERNAME\$user""))"

  foreach($d in @($worktree,$anchor,$tcb,$runid,$toolcopy,$scripts,$results)){ New-Item -ItemType Directory $d -Force | Out-Null }
  Set-Content "$anchor\seed.txt" "existing anchor record"
  Set-Content "$tcb\trusted_mod.py" 'MARKER="ORIGINAL"'
  Set-Content "$runid\id.json" '{"run":"director-run"}'
  Copy-Item "$SP\worker_probe.ps1" "$scripts\worker_probe.ps1" -Force

  # --- ACLs (allowlist by SID; explicit DENY on the sensitive stores) ---
  icacls $worktree /grant "*${sid}:(OI)(CI)M" /q | Out-Null
  icacls $results  /grant "*${sid}:(OI)(CI)M" /q | Out-Null
  icacls $scripts  /grant "*${sid}:(OI)(CI)RX" /q | Out-Null
  icacls $toolcopy /grant "*${sid}:(OI)(CI)RX" /q | Out-Null
  foreach($s in @($anchor,$tcb,$runid)){ icacls $s /grant "*${sid}:(OI)(CI)RX" /q | Out-Null }
  icacls $anchor /deny "*${sid}:(OI)(CI)(WD,AD,WDAC,WO,DE)" /q | Out-Null
  icacls $runid  /deny "*${sid}:(OI)(CI)(WD,AD,WDAC,WO,DE)" /q | Out-Null
  icacls $tcb    /deny "*${sid}:(OI)(CI)(WD,AD)" /q | Out-Null

  $rfile = Join-Path $worktree "result.txt"
  $ps = "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
  $cmd = "`"$ps`" -NoProfile -ExecutionPolicy Bypass -File `"$scripts\worker_probe.ps1`" -ResultsFile `"$rfile`" -DirectorPid $PID -Worktree `"$worktree`" -Anchor `"$anchor`" -Tcb `"$tcb`" -RunId `"$runid`" -ToolCopy `"$toolcopy`" -OpProfile `"$OpProfile`""
  O "launching worker via CreateProcessWithLogonW (Director PID=$PID, integrity High)..."
  $pwPtr = [System.Runtime.InteropServices.Marshal]::SecureStringToGlobalAllocUnicode($secure)
  try { $rc = [Launcher]::RunAs($user, ".", $pwPtr, $cmd, $results); O "worker launch rc=$rc" }
  finally { [System.Runtime.InteropServices.Marshal]::ZeroFreeGlobalAllocUnicode($pwPtr) }
  Start-Sleep -Milliseconds 800
  O ""
  O "===== WORKER RESULTS ====="
  if(Test-Path $rfile){ Get-Content $rfile | ForEach-Object { O $_ } } else { O "NO RESULT FILE (worker could not run / no access)" }
  O ""
  O "anchor after worker (expect only seed.txt): $(((Get-ChildItem $anchor).Name) -join ',')"
  O "tcb after worker (expect MARKER=ORIGINAL): $((Get-Content "$tcb\trusted_mod.py"))"
}
catch { O "ORCHESTRATOR ERROR: $($_.Exception.Message)" }
finally {
  O ""
  O "===== ROLLBACK ====="
  Get-Process powershell,cmd -ErrorAction SilentlyContinue | Where-Object { $_.Id -ne $PID } | ForEach-Object {}  # do not kill unrelated; worker already -Wait'ed
  if($worker){
    # remove the user's profile the proper way (Win32_UserProfile handles the junctions Directory.Delete chokes on)
    Get-CimInstance Win32_UserProfile -ErrorAction SilentlyContinue | Where-Object { $_.LocalPath -like '*GnosisWorkerProbe*' } | ForEach-Object { try { Remove-CimInstance $_ -ErrorAction Stop } catch {} }
    try { Remove-LocalUser -Name $user -ErrorAction Stop; O "user removed" } catch { O "user remove FAILED: $($_.Exception.Message)" }
    $prof = "C:\Users\$user"
    if(Test-Path $prof){ try { [System.IO.Directory]::Delete($prof,$true) } catch {} }
    O "profile removed=$(-not (Test-Path $prof))"
  } else { O "no user was created" }
  if(Test-Path $probe){ try { [System.IO.Directory]::Delete($probe,$true); O "probe dirs removed" } catch { O "probe dir remove: $($_.Exception.Message)" } }
  O "POST-FLIGHT: users(Gnosis*)=$(((Get-LocalUser -Name 'Gnosis*').Name) -join ',')  services(*Gnosis*)=$(((Get-Service -Name '*Gnosis*' -ErrorAction SilentlyContinue).Name) -join ',')  worker-profile-exists=$(Test-Path "C:\Users\$user")  probe-dir-exists=$(Test-Path $probe)  HEAD=$(& git -C "C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi" rev-parse --short HEAD)"
  Set-Content -Path $report -Value ($rep -join "`r`n") -Encoding UTF8
  O "report -> $report"
}