#Requires -Version 5.1

[CmdletBinding()]
param(
    [string]$Distro = "Ubuntu-22.04",
    [string]$LinuxUser = "",
    [string]$RobotAddress = "",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$wslExe = "$env:SystemRoot\System32\wsl.exe"
$dashboardUrl = "http://127.0.0.1:8000"

if ([string]::IsNullOrWhiteSpace($LinuxUser)) {
    & $wslExe -d $Distro -u root -- id -u fleetops 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $LinuxUser = "fleetops"
    }
    else {
        $LinuxUser = (& $wslExe -d $Distro -- id -un).Trim()
    }
}

$startScript = Join-Path $PSScriptRoot "start_control_stack.ps1"
$startArguments = @{
    Distro = $Distro
    LinuxUser = $LinuxUser
}
if (-not [string]::IsNullOrWhiteSpace($RobotAddress)) {
    $startArguments["RobotAddress"] = $RobotAddress
}
& $startScript @startArguments

if (-not $NoBrowser) {
    Start-Process $dashboardUrl
}

$tb1 = $null
foreach ($attempt in 0..10) {
    $payload = Invoke-RestMethod -Uri "$dashboardUrl/api/robots" -TimeoutSec 3
    $tb1 = @($payload.robots) |
        Where-Object { $_.robot_id -eq "tb1" } |
        Select-Object -First 1
    if ($null -ne $tb1 -and $tb1.online) {
        break
    }
    if ($attempt -lt 10) {
        Start-Sleep -Seconds 1
    }
}
if ($null -ne $tb1 -and $tb1.online) {
    $connection = "online"
    $status = "TB1_AUTO_CONNECTED"
}
else {
    $connection = "waiting-for-power-or-network"
    $status = "TB1_WAITING_FOR_POWER"
}

Write-Host "TB1_WEB_CONTROL_READY"
Write-Host "Dashboard=$dashboardUrl"
Write-Host "Connection=$connection"
Write-Host $status
Write-Host "The dashboard stays available and will update automatically when TB1 reconnects."
