# Idempotent teardown for the P2 service-SID publisher probe. Safe to run anytime.
$ErrorActionPreference = "Continue"
$svc  = "GnosisTrustedPublisherProbe"
$user = "GnosisP2Worker"
$pf   = "C:\Program Files\Gnosis\TrustProbe"
$pd   = "C:\ProgramData\Gnosis\TrustProbe"
$sc   = "$env:SystemRoot\System32\sc.exe"

# 1) stop + delete the probe service (its virtual account is removed with it)
$exists = [bool](Get-Service -Name $svc -ErrorAction SilentlyContinue)
if ($exists) {
  & $sc stop $svc *> $null
  for ($i=0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 300
    if ((& $sc query $svc 2>$null | Select-String "STOPPED") -ne $null) { break }
  }
  & $sc delete $svc *> $null
  Start-Sleep -Milliseconds 400
}

# 2) kill any stray publisher python still holding the trust root
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like "*TrustProbe*" } |
  ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }

# 3) remove the worker probe user + its profile
Get-CimInstance Win32_UserProfile -ErrorAction SilentlyContinue |
  Where-Object { $_.LocalPath -like "*\$user" } |
  ForEach-Object { try { Remove-CimInstance $_ -ErrorAction Stop } catch {} }
try { Remove-LocalUser -Name $user -ErrorAction Stop } catch {}

# 4) remove disposable trust roots (take ownership first for any restrictive ACLs)
foreach ($p in @($pf, $pd)) {
  if (Test-Path $p) {
    & "$env:SystemRoot\System32\takeown.exe" /f $p /r /a /d S *> $null
    & "$env:SystemRoot\System32\icacls.exe" $p /reset /t /q *> $null
    Get-ChildItem $p -Recurse -Force -ErrorAction SilentlyContinue | ForEach-Object { try { $_.Attributes='Normal' } catch {} }
    Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path $p) { try { [System.IO.Directory]::Delete($p, $true) } catch {} }
  }
}
# prune empty C:\Program Files\Gnosis and C:\ProgramData\Gnosis if we created them
foreach ($parent in @("C:\Program Files\Gnosis", "C:\ProgramData\Gnosis")) {
  if ((Test-Path $parent) -and -not (Get-ChildItem $parent -Force -ErrorAction SilentlyContinue)) {
    Remove-Item -LiteralPath $parent -Force -ErrorAction SilentlyContinue
  }
}

# 5) residual report
"svc_present   : " + ([bool](Get-Service -Name $svc -ErrorAction SilentlyContinue))
"user_present  : " + ([bool](Get-LocalUser -Name $user -ErrorAction SilentlyContinue))
"profile_left  : " + ([bool](Get-CimInstance Win32_UserProfile -ErrorAction SilentlyContinue | Where-Object { $_.LocalPath -like "*\$user" }))
"pf_left       : " + (Test-Path $pf)
"pd_left       : " + (Test-Path $pd)
"gnosis_svcs   : " + (((Get-Service -Name '*Gnosis*' -ErrorAction SilentlyContinue).Name) -join ',')
"gnosis_users  : " + (((Get-LocalUser -Name 'Gnosis*' -ErrorAction SilentlyContinue).Name) -join ',')
"gnosis_tasks  : " + (((Get-ScheduledTask -TaskName '*Gnosis*' -ErrorAction SilentlyContinue).TaskName) -join ',')
