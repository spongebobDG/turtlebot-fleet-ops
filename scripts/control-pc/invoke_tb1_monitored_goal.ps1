#Requires -Version 5.1

[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$RobotId = "tb1",
    [Parameter(Mandatory = $true)]
    [double]$X,
    [Parameter(Mandatory = $true)]
    [double]$Y,
    [Parameter(Mandatory = $true)]
    [double]$Yaw,
    [double]$CancelAfterSec = -1.0,
    [double]$TimeoutSec = 60.0,
    [double]$MinScanM = 0.19,
    [double]$MaxObservedLinearMps = 0.06,
    [double]$MaxObservedAngularRadps = 0.32,
    [ValidateRange(50, 1000)]
    [int]$PollMs = 200,
    [switch]$ConfirmWarnings
)

$ErrorActionPreference = "Stop"
$terminalStates = @("SUCCEEDED", "CANCELED", "FAILED", "LEASE_EXPIRED")

function Get-RobotSnapshot {
    $response = Invoke-RestMethod -Uri "$BaseUrl/api/robots"
    $robot = @($response.robots) |
        Where-Object { $_.robot_id -eq $RobotId } |
        Select-Object -First 1
    if ($null -eq $robot) {
        throw "Robot '$RobotId' is missing from the Gateway snapshot."
    }
    return $robot
}

function Set-EmergencyStop {
    param([bool]$Engaged)

    $body = @{ engaged = $Engaged } | ConvertTo-Json -Compress
    return Invoke-RestMethod `
        -Method Post `
        -Uri "$BaseUrl/api/robots/$RobotId/estop" `
        -ContentType "application/json" `
        -Body $body
}

function Engage-EmergencyStopSafely {
    try {
        Set-EmergencyStop -Engaged $true | Out-Null
    }
    catch {
        Write-Warning "Failed to engage e-stop through the Gateway: $($_.Exception.Message)"
    }
}

function Assert-SafeTelemetry {
    param([object]$Robot)

    $linear = [math]::Abs([double]$Robot.odom.linear_velocity)
    $angular = [math]::Abs([double]$Robot.odom.angular_velocity)
    $scan = [double]$Robot.scan.min_range
    if (-not [bool]$Robot.online) {
        throw "Robot went offline during the monitored goal."
    }
    if (-not [bool]$Robot.scan.fresh -or -not [bool]$Robot.scan.valid) {
        throw "LiDAR became stale or invalid during the monitored goal."
    }
    if ($linear -gt $MaxObservedLinearMps) {
        throw "Observed linear velocity $linear exceeds $MaxObservedLinearMps m/s."
    }
    if ($angular -gt $MaxObservedAngularRadps) {
        throw "Observed angular velocity $angular exceeds $MaxObservedAngularRadps rad/s."
    }
    if ($scan -lt $MinScanM) {
        throw "LiDAR minimum $scan is below $MinScanM m."
    }
}

$preflight = Get-RobotSnapshot
if (-not [bool]$preflight.online) {
    throw "Robot '$RobotId' is offline."
}
if ([bool]$preflight.safety.estop_active -or -not [bool]$preflight.safety.motion_armed) {
    throw "Release e-stop and verify neutral rearm before sending a monitored goal."
}
if ($preflight.navigation.state -notin @("READY", "SUCCEEDED", "CANCELED")) {
    throw "Navigation is not ready: $($preflight.navigation.state)."
}
if (-not [string]::IsNullOrWhiteSpace([string]$preflight.navigation.active_command_id)) {
    throw "An active navigation command already exists."
}
Assert-SafeTelemetry -Robot $preflight

$goalBody = @{
    x = $X
    y = $Y
    yaw = $Yaw
    confirm_warnings = [bool]$ConfirmWarnings
} | ConvertTo-Json -Compress

$commandId = $null
$cancelRequested = $false
$cancelHttpStatus = $null
$maxLinear = 0.0
$maxAngular = 0.0
$minScan = [double]::PositiveInfinity
$stateHistory = New-Object System.Collections.Generic.List[string]
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$final = $null

try {
    $goal = Invoke-RestMethod `
        -Method Post `
        -Uri "$BaseUrl/api/robots/$RobotId/navigation/goals" `
        -ContentType "application/json" `
        -Body $goalBody
    $commandId = [string]$goal.command_id

    while ($stopwatch.Elapsed.TotalSeconds -lt $TimeoutSec) {
        Start-Sleep -Milliseconds $PollMs
        $robot = Get-RobotSnapshot
        Assert-SafeTelemetry -Robot $robot

        $linear = [math]::Abs([double]$robot.odom.linear_velocity)
        $angular = [math]::Abs([double]$robot.odom.angular_velocity)
        $scan = [double]$robot.scan.min_range
        $maxLinear = [math]::Max($maxLinear, $linear)
        $maxAngular = [math]::Max($maxAngular, $angular)
        $minScan = [math]::Min($minScan, $scan)

        $state = [string]$robot.navigation.state
        if ($stateHistory.Count -eq 0 -or $stateHistory[$stateHistory.Count - 1] -ne $state) {
            $stateHistory.Add($state)
        }

        if (
            $CancelAfterSec -ge 0.0 -and
            -not $cancelRequested -and
            $stopwatch.Elapsed.TotalSeconds -ge $CancelAfterSec -and
            $state -notin $terminalStates
        ) {
            $cancelResponse = Invoke-WebRequest `
                -UseBasicParsing `
                -Method Delete `
                -Uri "$BaseUrl/api/robots/$RobotId/navigation/goals/$commandId"
            $cancelHttpStatus = [int]$cancelResponse.StatusCode
            $cancelRequested = $true
        }

        if ($state -in $terminalStates) {
            $final = $robot
            break
        }
    }

    if ($null -eq $final) {
        throw "Goal $commandId exceeded the $TimeoutSec second monitor timeout."
    }

    $expectedState = "SUCCEEDED"
    if ($CancelAfterSec -ge 0.0) {
        $expectedState = "CANCELED"
    }
    if ([string]$final.navigation.state -ne $expectedState) {
        throw "Goal $commandId ended as $($final.navigation.state), expected $expectedState."
    }

    $quietMaxLinear = 0.0
    $quietMaxAngular = 0.0
    Start-Sleep -Seconds 2
    for ($index = 0; $index -lt 20; $index++) {
        Start-Sleep -Milliseconds 100
        $quietRobot = Get-RobotSnapshot
        Assert-SafeTelemetry -Robot $quietRobot
        $quietMaxLinear = [math]::Max(
            $quietMaxLinear,
            [math]::Abs([double]$quietRobot.odom.linear_velocity)
        )
        $quietMaxAngular = [math]::Max(
            $quietMaxAngular,
            [math]::Abs([double]$quietRobot.odom.angular_velocity)
        )
    }

    if (-not [string]::IsNullOrWhiteSpace([string]$quietRobot.navigation.active_command_id)) {
        throw "Goal reached a terminal state but active_command_id is not empty."
    }

    [pscustomobject]@{
        RobotId = $RobotId
        CommandId = $commandId
        Mode = if ($CancelAfterSec -ge 0.0) { "CANCEL" } else { "SUCCESS" }
        StateHistory = $stateHistory -join "->"
        FinalState = [string]$final.navigation.state
        CancelRequested = $cancelRequested
        CancelHttpStatus = $cancelHttpStatus
        DurationSec = [math]::Round($stopwatch.Elapsed.TotalSeconds, 3)
        MaxObservedLinearMps = [math]::Round($maxLinear, 6)
        MaxObservedAngularRadps = [math]::Round($maxAngular, 6)
        MinimumScanM = [math]::Round($minScan, 3)
        QuietMaxLinearMps = [math]::Round($quietMaxLinear, 6)
        QuietMaxAngularRadps = [math]::Round($quietMaxAngular, 6)
        MapX = [math]::Round([double]$quietRobot.navigation.current.x, 4)
        MapY = [math]::Round([double]$quietRobot.navigation.current.y, 4)
        MapYaw = [math]::Round([double]$quietRobot.navigation.current.yaw, 4)
        Recoveries = [int]$final.navigation.number_of_recoveries
        EstopActive = [bool]$quietRobot.safety.estop_active
        MotionArmed = [bool]$quietRobot.safety.motion_armed
    }
}
catch {
    Engage-EmergencyStopSafely
    throw
}
