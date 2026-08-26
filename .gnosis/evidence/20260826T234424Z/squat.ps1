param($PipeShort,$Marker)
# Runs AS THE WORKER. Pre-creates a pipe with the publisher's name and holds it,
# to prove the legitimate service refuses to attach (FILE_FLAG_FIRST_PIPE_INSTANCE).
$ErrorActionPreference = "Continue"
try {
  $s = New-Object System.IO.Pipes.NamedPipeServerStream($PipeShort, [System.IO.Pipes.PipeDirection]::InOut)
  Set-Content -LiteralPath $Marker -Value "WORKER-CREATED-PIPE"
  Start-Sleep -Seconds 10
  $s.Dispose()
} catch {
  Set-Content -LiteralPath $Marker -Value ("WORKER-DENIED:" + $_.Exception.GetType().Name)
}
