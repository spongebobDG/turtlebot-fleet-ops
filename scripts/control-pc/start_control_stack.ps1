#Requires -Version 5.1

[CmdletBinding()]
param(
    [string]$Distro = "Ubuntu-22.04",
    [string]$LinuxUser = "fleetops",
    [string]$RobotAddress = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$outputDir = Join-Path $repoRoot "output"
$markerPath = Join-Path $outputDir "control-pc-runtime.txt"
$wslExe = "$env:SystemRoot\System32\wsl.exe"
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

function Get-FleetRobots {
    param([int]$TimeoutSec = 2)

    $payload = Invoke-RestMethod `
        -Uri "http://127.0.0.1:8000/api/robots" `
        -TimeoutSec $TimeoutSec
    if ($null -eq $payload) {
        return @()
    }
    $robotsProperty = $payload.PSObject.Properties["robots"]
    if ($null -ne $robotsProperty) {
        return @($robotsProperty.Value)
    }
    return @($payload)
}

function Assert-ControlTimeReady {
    $stripchart = & "$env:SystemRoot\System32\w32tm.exe" `
        /stripchart /computer:time.google.com /dataonly /samples:2 2>&1
    $offsets = @(
        $stripchart |
            ForEach-Object {
                [regex]::Match($_.ToString(), "(?<offset>[+-]\d+[\.,]\d+)s")
            } |
            Where-Object { $_.Success } |
            ForEach-Object {
                [double]::Parse(
                    $_.Groups["offset"].Value.TrimEnd("s").Replace(",", "."),
                    [Globalization.CultureInfo]::InvariantCulture
                )
            }
    )
    if ($LASTEXITCODE -ne 0 -or $offsets.Count -eq 0) {
        throw "Could not verify Windows time against NTP. Check the network and Windows Time service."
    }
    $windowsOffsetSec = [double]$offsets[-1]
    if ([Math]::Abs($windowsOffsetSec) -gt 0.2) {
        throw (
            "Windows clock offset is $windowsOffsetSec seconds. Run an Administrator PowerShell: " +
            "scripts\control-pc\configure_windows_time.ps1"
        )
    }

    $before = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0
    $wslEpochNs = (& $wslExe -d $Distro -u $LinuxUser -- date +%s%N).Trim()
    $after = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0
    [double]$wslEpochSec = 0.0
    if (
        $LASTEXITCODE -ne 0 -or
        -not [double]::TryParse(
            $wslEpochNs,
            [Globalization.NumberStyles]::Integer,
            [Globalization.CultureInfo]::InvariantCulture,
            [ref]$wslEpochSec
        )
    ) {
        throw "Could not compare WSL and Windows clocks."
    }
    $wslEpochSec /= 1000000000.0
    $windowsMidpointSec = ($before + $after) / 2.0
    $wslOffsetSec = $wslEpochSec - $windowsMidpointSec
    if ([Math]::Abs($wslOffsetSec) -gt 0.2) {
        throw (
            "WSL clock differs from Windows by $([Math]::Round($wslOffsetSec, 3)) seconds. " +
            "Let NTP settle or restart WSL before starting robot control."
        )
    }
    Write-Host (
        "CONTROL_TIME_READY windows_ntp_offset=$([Math]::Round($windowsOffsetSec, 4))s " +
        "wsl_windows_offset=$([Math]::Round($wslOffsetSec, 4))s"
    )
}

if ($LinuxUser -notmatch '^[A-Za-z_][A-Za-z0-9_-]*$') {
    throw "Invalid WSL user name: $LinuxUser"
}
if (
    -not [string]::IsNullOrWhiteSpace($RobotAddress) -and
    $RobotAddress -notmatch '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
) {
    throw "Invalid robot host name or address: $RobotAddress"
}

& $wslExe -d $Distro -u root -- id -u $LinuxUser 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "WSL user '$LinuxUser' is not prepared. Run scripts\control-pc\bootstrap_wsl.ps1 once."
}

Assert-ControlTimeReady

& $wslExe -d $Distro -u $LinuxUser -- bash -lc `
    "test -r ~/.config/turtlebot-fleet-ops/control.env && systemctl --user cat fleet-control-zenoh.service fleet-gateway.service fleet-log-mlops.service >/dev/null"
if ($LASTEXITCODE -ne 0) {
    throw "The production control services are not installed for '$LinuxUser'. Run scripts\control-pc\bootstrap_wsl.ps1 once."
}

try {
    $existingRobots = @(Get-FleetRobots -TimeoutSec 2)
}
catch {
    $existingRobots = @()
}
if ($existingRobots | Where-Object { $_.hostname -eq "robotless-mock" }) {
    Write-Host "Stopping the robotless mock before production startup..."
    & $wslExe -d $Distro -u root -- bash -lc `
        "pkill -INT -f '[r]os2 launch fleet_gateway weekend_mock.launch.py' || true"
    foreach ($attempt in 1..15) {
        try {
            Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 1 | Out-Null
            Start-Sleep -Seconds 1
        }
        catch {
            break
        }
    }
}

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

if (-not [string]::IsNullOrWhiteSpace($RobotAddress)) {
    $updateAddress = "set -e; " +
        "sed -i -E 's/^ROBOT_ADDRESS=.*/ROBOT_ADDRESS=$RobotAddress/' ~/.config/turtlebot-fleet-ops/control.env; " +
        "chmod 0600 ~/.config/turtlebot-fleet-ops/control.env"
    & $wslExe -d $Distro -u $LinuxUser -- bash -lc $updateAddress
    if ($LASTEXITCODE -ne 0) {
        throw "Could not update the production robot address."
    }
}

& $wslExe -d $Distro -u $LinuxUser -- `
    bash -lc "systemctl --user start fleet-control-zenoh.service fleet-gateway.service fleet-log-mlops.service"
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
        fleet-control-zenoh.service fleet-gateway.service fleet-log-mlops.service
    throw "Fleet Gateway did not become healthy within 90 seconds."
}

$robots = @(Get-FleetRobots -TimeoutSec 3)
if ($robots | Where-Object { $_.hostname -eq "robotless-mock" }) {
    throw "Port 8000 still belongs to the robotless mock; production Gateway was not started."
}

$localAiState = "UNAVAILABLE"
$localAiModel = "qwen3:8b"
try {
    $localAi = Invoke-RestMethod `
        -Uri "http://127.0.0.1:8000/api/mlops/ros2-logs/ai" `
        -TimeoutSec 5
    $localAiState = [string]$localAi.state
    $localAiModel = [string]$localAi.model
    if ($localAiState -ne "READY") {
        Write-Warning "Local log AI is $localAiState ($($localAi.message)). Dashboard and robot control remain available."
    }
}
catch {
    Write-Warning "Could not read local log AI status. Dashboard and robot control remain available."
}

$configuredAddress = (& $wslExe -d $Distro -u $LinuxUser -- bash -lc `
    "sed -n 's/^ROBOT_ADDRESS=//p' ~/.config/turtlebot-fleet-ops/control.env | head -n 1").Trim()

$result = @(
    "CONTROL_PC_RUNTIME_OK",
    "Timestamp=$([DateTimeOffset]::Now.ToString('o'))",
    "Distro=$Distro",
    "LinuxUser=$LinuxUser",
    "RobotAddress=$configuredAddress",
    "KeepAliveProcessId=$keepAliveProcessId",
    "KeepAliveStartTimeUtc=$($keepAliveStartTimeUtc.ToString('o'))",
    "Dashboard=http://localhost:8000",
    "LocalLogAI=$localAiState",
    "LocalLogAIModel=$localAiModel"
)
Set-Content -LiteralPath $markerPath -Value $result -Encoding UTF8
$result | ForEach-Object { Write-Host $_ }
