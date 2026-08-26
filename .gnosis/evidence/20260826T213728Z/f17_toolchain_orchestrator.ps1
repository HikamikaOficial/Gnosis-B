$ErrorActionPreference = "Continue"
Add-Type @"
using System; using System.Runtime.InteropServices;
public class TL {
  [StructLayout(LayoutKind.Sequential)] public struct SI {
    public int cb; public string r1,desktop,title; public int x,y,xs,ys,xc,yc,fill,flags;
    public short show,r2; public IntPtr r3,hIn,hOut,hErr; }
  [StructLayout(LayoutKind.Sequential)] public struct PI { public IntPtr hProcess,hThread; public int pid,tid; }
  [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
  static extern bool CreateProcessWithLogonW(string u,string d,IntPtr pw,uint lf,string app,string cmd,uint cf,IntPtr env,string cd,ref SI si,out PI pi);
  [DllImport("kernel32.dll")] static extern uint WaitForSingleObject(IntPtr h,uint ms);
  [DllImport("kernel32.dll")] static extern bool GetExitCodeProcess(IntPtr h,out uint c);
  [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
  public static int RunAs(string user,string domain,IntPtr pw,string cmd,string cd){
    var si=new SI(); si.cb=Marshal.SizeOf(si); PI pi;
    if(!CreateProcessWithLogonW(user,domain,pw,1u,null,cmd,0x400u,IntPtr.Zero,cd,ref si,out pi)) return -Marshal.GetLastWin32Error();
    WaitForSingleObject(pi.hProcess,200000); uint code; GetExitCodeProcess(pi.hProcess,out code);
    CloseHandle(pi.hProcess); CloseHandle(pi.hThread); return (int)code;
  }
}
"@
$SP    = "C:\Users\nicol\AppData\Local\Temp\claude\C--Users-nicol-Desktop-Claude-Code-Proyectos-GnosisAgentAi\6ff48a69-99d0-47f4-96c7-ff4ce9d8b55d\scratchpad"
$probe = "C:\ProgramData\GnosisWorkerTCprobe"
$toolroot = "C:\ProgramData\GnosisWorkerToolchainProbe"
$user  = "GnosisWorkerProbe"
$OpProfile = "C:\Users\nicol"
$report = Join-Path $SP "TOOLCHAIN-RESULTS.txt"
$rep = New-Object System.Collections.ArrayList
function O($m){ [void]$rep.Add([string]$m); Write-Output $m }
O "PRE-FLIGHT: HEAD=$(& git -C 'C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi' rev-parse --short HEAD) users(Gnosis*)=$(((Get-LocalUser -Name 'Gnosis*' -ErrorAction SilentlyContinue).Name) -join ',') toolroot=$(Test-Path $toolroot)"
if(Test-Path $probe){ [System.IO.Directory]::Delete($probe,$true) }
$worktree=Join-Path $probe "worktree"; $scripts=Join-Path $probe "scripts"
$worker=$false
try {
  $secure = New-Object System.Security.SecureString
  foreach($c in "Aa1!".ToCharArray()){ $secure.AppendChar($c) }
  $rb = New-Object 'byte[]' 20; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($rb)
  foreach($b in $rb){ $secure.AppendChar([char](65 + ($b % 26))) }
  $secure.MakeReadOnly(); [Array]::Clear($rb,0,$rb.Length)
  New-LocalUser -Name $user -Password $secure -FullName "F17 tc probe" -Description "delete after" -AccountNeverExpires -UserMayNotChangePassword | Out-Null
  $worker=$true
  Add-LocalGroupMember -Group "Usuarios" -Member $user -ErrorAction SilentlyContinue
  $sid=(Get-LocalUser $user).SID.Value
  O "user $user SID=$sid admin=$([bool]((Get-LocalGroupMember 'Administradores' -ErrorAction SilentlyContinue).Name -contains ""$env:COMPUTERNAME\$user""))"
  foreach($d in @($worktree,$scripts)){ New-Item -ItemType Directory $d -Force | Out-Null }
  Copy-Item "$SP\worker_toolchain.ps1" "$scripts\worker_toolchain.ps1" -Force
  icacls $worktree /grant "*${sid}:(OI)(CI)M" /q | Out-Null
  icacls $scripts  /grant "*${sid}:(OI)(CI)RX" /q | Out-Null
  $rfile = Join-Path $worktree "tc_result.txt"
  $ps = "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
  $cmd = "`"$ps`" -NoProfile -ExecutionPolicy Bypass -File `"$scripts\worker_toolchain.ps1`" -ResultsFile `"$rfile`" -Worktree `"$worktree`" -ToolRoot `"$toolroot`" -OpProfile `"$OpProfile`""
  O "launching worker toolchain probe..."
  $pwPtr = [System.Runtime.InteropServices.Marshal]::SecureStringToGlobalAllocUnicode($secure)
  try { $rc=[TL]::RunAs($user,".",$pwPtr,$cmd,$worktree); O "worker rc=$rc" } finally { [System.Runtime.InteropServices.Marshal]::ZeroFreeGlobalAllocUnicode($pwPtr) }
  Start-Sleep -Milliseconds 800
  O "===== TOOLCHAIN RESULTS ====="
  if(Test-Path $rfile){ Get-Content $rfile | ForEach-Object { O $_ } } else { O "NO RESULT FILE" }
}
catch { O "ORCH ERROR: $($_.Exception.Message)" }
finally {
  O "===== ROLLBACK ====="
  if($worker){
    Get-CimInstance Win32_UserProfile -ErrorAction SilentlyContinue | Where-Object { $_.LocalPath -like '*GnosisWorkerProbe*' } | ForEach-Object { try { Remove-CimInstance $_ -ErrorAction Stop } catch {} }
    try { Remove-LocalUser -Name $user -ErrorAction Stop; O "user removed" } catch { O "user remove FAILED: $($_.Exception.Message)" }
    if(Test-Path "C:\Users\$user"){ try { [System.IO.Directory]::Delete("C:\Users\$user",$true) } catch {} }
  }
  if(Test-Path $probe){ try { Remove-Item -LiteralPath $probe -Recurse -Force -ErrorAction Stop } catch { try { [System.IO.Directory]::Delete($probe,$true) } catch {} } }
  O "POST-FLIGHT: users=$(((Get-LocalUser -Name 'Gnosis*' -ErrorAction SilentlyContinue).Name) -join ',') workerprofile=$(Test-Path "C:\Users\$user") probedir=$(Test-Path $probe) HEAD=$(& git -C 'C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi' rev-parse --short HEAD)"
  Set-Content -Path $report -Value ($rep -join "`r`n") -Encoding UTF8
  O "report -> $report"
}
