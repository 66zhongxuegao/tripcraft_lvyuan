[CmdletBinding()]
param(
    [int]$IntervalMinutes = 20
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$watchdog = Join-Path $PSScriptRoot "tunnel_watchdog.ps1"
if (-not (Test-Path -LiteralPath $watchdog)) { throw "Watchdog script not found: $watchdog" }

$startup = [Environment]::GetFolderPath("Startup")
if ([string]::IsNullOrWhiteSpace($startup)) { throw "Cannot locate the current user's Startup folder" }
$vbs = Join-Path $startup "TripCraft Demo Tunnel Watchdog.vbs"
$command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$watchdog`" -Loop -IntervalMinutes $IntervalMinutes"
$escaped = $command.Replace('"', '""')
$vbsContent = @"
Set shell = CreateObject("WScript.Shell")
shell.Run "$escaped", 0, False
"@
Set-Content -LiteralPath $vbs -Value $vbsContent -Encoding Unicode
Write-Output "Installed startup entry: $vbs"
Write-Output "It will start automatically after user logon and check every $IntervalMinutes minutes."

# Stop any previous watchdog instance so the new one can acquire the mutex.
$existing = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -match "[\\/]tunnel_watchdog\.ps1" }
foreach ($p in @($existing)) {
    try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; Write-Output "Stopped old watchdog pid=$($p.ProcessId)" } catch {}
}
Start-Sleep -Seconds 1
Start-Process -FilePath "wscript.exe" -ArgumentList @("`"$vbs`"") -WindowStyle Hidden
Write-Output "Started the background watchdog now."
