param($ResultsFile,$PipeShort,$Svc,$Pf,$Pd,$PubPid,$WorkDir)
# Runs AS THE WORKER (distinct SID). Every action here uses the worker's token,
# so each result is the OS's real answer for a malicious/compromised worker (T2).
$ErrorActionPreference = "Continue"
function Emit($k,$v){ try { Add-Content -LiteralPath $ResultsFile -Value ("{0} = {1}" -f $k,$v) } catch {} }
try { Set-Content -LiteralPath $ResultsFile -Value ("WORKER = " + (& C:\Windows\System32\whoami.exe)) -ErrorAction Stop } catch {}

function Send($msg){
  try {
    # Request ONLY ReadData|WriteData|Synchronize, never GENERIC_WRITE (whose
    # FILE_CREATE_PIPE_INSTANCE bit the pipe DACL deliberately withholds).
    $rights = [System.IO.Pipes.PipeAccessRights]'ReadData, WriteData, Synchronize'
    $c = New-Object System.IO.Pipes.NamedPipeClientStream('.', $PipeShort, $rights,
          [System.IO.Pipes.PipeOptions]::None,
          [System.Security.Principal.TokenImpersonationLevel]::None,
          [System.IO.HandleInheritability]::None)
    $c.Connect(4000)
    try { $c.ReadMode = [System.IO.Pipes.PipeTransmissionMode]::Message } catch {}
    $b = [Text.Encoding]::UTF8.GetBytes($msg); $c.Write($b,0,$b.Length); $c.Flush()
    $buf = New-Object byte[] 512; $n = $c.Read($buf,0,512); $c.Dispose()
    return [Text.Encoding]::UTF8.GetString($buf,0,$n).Trim()
  } catch { return "SEND-ERR:$($_.Exception.GetType().Name)" }
}

# --- IPC protocol tests (authorized connect via pipe DACL) ---
Emit "01_legit_publish"      (Send "PUBLISH run_A")
Emit "02_duplicate"          (Send "PUBLISH run_A")
Emit "03_cross_run_ownerB"   (Send "PUBLISH run_B")
Emit "04_unknown_run"        (Send "PUBLISH run_ZZZ")
Emit "05_bad_verb"           (Send "HELLO run_A")
Emit "06_bad_run_id"         (Send "PUBLISH ../../etc")
Emit "07_oversized"          (Send ("PUBLISH " + ("x"*600)))

# --- worker tries to CREATE the pipe (needs FILE_CREATE_PIPE_INSTANCE, denied) ---
try {
  $srv = New-Object System.IO.Pipes.NamedPipeServerStream($PipeShort,[System.IO.Pipes.PipeDirection]::InOut)
  Emit "08_worker_create_pipe" "CREATED (BAD)"; $srv.Dispose()
} catch { Emit "08_worker_create_pipe" ("DENIED:" + $_.Exception.GetType().Name) }

# --- filesystem writes to the trust plane (worker has no ACE) ---
function TryWrite($k,$path){ try { Set-Content -LiteralPath $path -Value "x" -ErrorAction Stop; Emit $k "WRITABLE (BAD)" } catch { Emit $k ("DENIED:" + $_.Exception.GetType().Name) } }
TryWrite "09_write_service_main" "$Pf\publisher\main.py"
TryWrite "10_write_trust_python" "$Pf\runtime\python.exe"
TryWrite "11_write_anchor_code"  "$Pf\publisher\gnosis\kernel\authority.py"
TryWrite "12_write_runidentity"  "$Pd\runidentity\run_A.json"
TryWrite "13_write_anchorstore"  "$Pd\anchors\anchors.jsonl"
TryWrite "14_plant_shadow_mod"   "$Pf\publisher\evilmod.py"

# --- service-control attacks (worker should have NO rights on the service object) ---
$sc="C:\Windows\System32\sc.exe"
Emit "15_svc_change_config" ((& $sc config $Svc binPath= "C:\evil.exe" 2>&1 | Select-String "DENEGADO|DENIED|5:|OpenService") -join ' ')
Emit "16_svc_stop"          ((& $sc stop   $Svc 2>&1 | Select-String "DENEGADO|DENIED|5:|OpenService") -join ' ')
Emit "17_svc_delete"        ((& $sc delete $Svc 2>&1 | Select-String "DENEGADO|DENIED|5:|OpenService") -join ' ')

# --- process attack: open the publisher with dangerous rights ---
Add-Type @"
using System; using System.Runtime.InteropServices;
public class PA { [DllImport("kernel32.dll", SetLastError=true)] public static extern IntPtr OpenProcess(uint a, bool inh, uint pid);
  [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);
  [DllImport("kernel32.dll")] public static extern uint GetLastError(); }
"@
function OpenProc($k,$access){ $h=[PA]::OpenProcess($access,$false,[uint32]$PubPid); if($h -ne [IntPtr]::Zero){ Emit $k "OPENED (BAD)"; [PA]::CloseHandle($h) } else { Emit $k ("DENIED err=" + [PA]::GetLastError()) } }
if ($PubPid -gt 0) {
  OpenProc "18_open_vm_write"     0x0020   # PROCESS_VM_WRITE
  OpenProc "19_open_dup_handle"   0x0040   # PROCESS_DUP_HANDLE
  OpenProc "20_open_create_thread"0x0002   # PROCESS_CREATE_THREAD
  OpenProc "21_open_vm_operation" 0x0008   # PROCESS_VM_OPERATION
  OpenProc "22_open_create_proc"  0x0080   # PROCESS_CREATE_PROCESS
} else { Emit "18_open_vm_write" "no-pubpid" }

Emit "DONE" "1"
