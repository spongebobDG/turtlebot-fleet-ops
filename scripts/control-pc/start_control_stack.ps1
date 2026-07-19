#Requires -Version 5.1

[CmdletBinding()]
param(
    [string]$Distro = "Ubuntu-22.04",
    [string]$LinuxUser = "fleetops"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$outputDir = Join-Path $repoRoot "output"
$markerPath = Join-Path $outputDir "control-pc-runtime.txt"
$wslExe = "$env:SystemRoot\System32\wsl.exe"
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

# WSL stops the distribution after the last Windows-side wsl.exe client exits,
# even when systemd user services are still active. Keep one hidden client alive
# so the Gateway and Zenoh bridge survive after this login script exits.
$keepAliveProcess = $null
if (Test-Path -LiteralPath $markerPath) {
    $processIdLine = Get-Content -LiteralPath $markerPath |
        Where-Object { $_ -like "KeepAliveProcessId=*" } |
        Select-Object -First 1
    $processStartLine = Get-Content -LiteralPath $markerPath |
        Where-Object { $_ -like "KeepAliveStartTimeUtc=*" } |
        Select-Object -First 1
    if ($null -ne $processIdLine -and $null -ne $processStartLine) {
        $recordedProcessId = 0
        $recordedStartTime = [DateTimeOffset]::MinValue
        if (
            [int]::TryParse(($processIdLine -split "=", 2)[1], [ref]$recordedProcessId) -and
            [DateTimeOffset]::TryParse(
                ($processStartLine -split "=", 2)[1],
                [ref]$recordedStartTime
            )
        ) {
            $candidate = Get-Process -Id $recordedProcessId -ErrorAction SilentlyContinue
            if (
                $null -ne $candidate -and
                $candidate.ProcessName -eq "wsl" -and
                $candidate.StartTime.ToUniversalTime() -eq $recordedStartTime.UtcDateTime
            ) {
                $keepAliveProcess = $candidate
            }
        }
    }
}
if ($null -eq $keepAliveProcess) {
    $startedKeepAlive = Start-Process `
        -FilePath $wslExe `
        -ArgumentList @("-d", $Distro, "-u", $LinuxUser, "--", "sleep", "infinity") `
        -WindowStyle Hidden `
        -PassThru
    Start-Sleep -Seconds 2
    if ($startedKeepAlive.HasExited) {
        throw "The WSL keepalive process exited during startup."
    }
    $keepAliveProcessId = $startedKeepAlive.Id
    $keepAliveStartTimeUtc = $startedKeepAlive.StartTime.ToUniversalTime()
}
else {
    $keepAliveProcessId = $keepAliveProcess.Id
    $keepAliveStartTimeUtc = $keepAliveProcess.StartTime.ToUniversalTime()
}

& $wslExe -d $Distro -u $LinuxUser -- `
    bash -lc "systemctl --user start fleet-control-zenoh.service fleet-gateway.service"
if ($LASTEXITCODE -ne 0) {
    throw "Could not start the WSL fleet control services."
}

$healthy = $false
foreach ($attempt in 1..90) {
    try {
        $response = Invoke-RestMethod `
            -Uri "http://127.0.0.1:8000/api/health" `
            -TimeoutSec 2
        if ($null -ne $response) {
            $healthy = $true
            break
        }
    }
    catch {
        Start-Sleep -Seconds 1
    }
}

if (-not $healthy) {
    & $wslExe -d $Distro -u $LinuxUser -- `
        systemctl --user --no-pager --full status `
        fleet-control-zenoh.service fleet-gateway.service
    throw "Fleet Gateway did not become healthy within 90 seconds."
}

$result = @(
    "CONTROL_PC_RUNTIME_OK",
    "Timestamp=$([DateTimeOffset]::Now.ToString('o'))",
    "Distro=$Distro",
    "KeepAliveProcessId=$keepAliveProcessId",
    "KeepAliveStartTimeUtc=$($keepAliveStartTimeUtc.ToString('o'))",
    "Dashboard=http://localhost:8000"
)
Set-Content -LiteralPath $markerPath -Value $result -Encoding UTF8
$result | ForEach-Object { Write-Host $_ }
