#Requires -Version 5.1

[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$RobotId = "tb1",
    [Parameter(Mandatory = $true)]
    [long]$SinceEpoch,
    [ValidateRange(60, 3600)]
    [int]$DurationSec = 900,
    [ValidateRange(20, 300)]
    [int]$GoalIntervalSec = 75,
    [ValidateRange(0.10, 0.20)]
    [double]$GoalOffsetM = 0.12,
    [ValidateRange(0.30, 1.00)]
    [double]$FrontClearanceM = 0.45
)

$ErrorActionPreference = "Stop"
$monitorScript = Join-Path $PSScriptRoot "invoke_tb1_monitored_goal.ps1"
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$goalCount = 0
$nextGoalSec = 0.0
$maxIdleLinear = 0.0
$maxIdleAngular = 0.0
$minimumScan = [double]::PositiveInfinity

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
    $body = @{ engaged = $true } | ConvertTo-Json -Compress
    Invoke-RestMethod `
        -Method Post `
        -Uri "$BaseUrl/api/robots/$RobotId/estop" `
        -ContentType "application/json" `
        -Body $body | Out-Null
}

function Get-FrontClearance {
    $scan = Invoke-RestMethod -Uri "$BaseUrl/api/robots/$RobotId/scan"
    if (-not [bool]$scan.fresh -or [int]$scan.valid_points -lt 40) {
        throw "LiDAR endpoint snapshot is stale or too sparse."
    }

    $front = [double]::PositiveInfinity
    foreach ($point in $scan.points) {
        $pointX = [double]$point[0]
        $pointY = [double]$point[1]
        $angleDeg = [math]::Atan2($pointY, $pointX) * 180.0 / [math]::PI
        if ([math]::Abs($angleDeg) -le 30.0) {
            $distance = [math]::Sqrt($pointX * $pointX + $pointY * $pointY)
            $front = [math]::Min($front, $distance)
        }
    }
    return $front
}

try {
    while ($stopwatch.Elapsed.TotalSeconds -lt $DurationSec) {
        $robot = Get-RobotSnapshot
        $linear = [math]::Abs([double]$robot.odom.linear_velocity)
        $angular = [math]::Abs([double]$robot.odom.angular_velocity)
        $scanMinimum = [double]$robot.scan.min_range
        $maxIdleLinear = [math]::Max($maxIdleLinear, $linear)
        $maxIdleAngular = [math]::Max($maxIdleAngular, $angular)
        $minimumScan = [math]::Min($minimumScan, $scanMinimum)

        if (-not [bool]$robot.online) {
            throw "Robot went offline during baseline collection."
        }
        if ([bool]$robot.safety.estop_active -or -not [bool]$robot.safety.motion_armed) {
            throw "Motion safety became disarmed during baseline collection."
        }
        if (-not [bool]$robot.scan.fresh -or $scanMinimum -lt 0.16) {
            throw "LiDAR safety precondition failed during baseline collection."
        }
        if (-not [string]::IsNullOrWhiteSpace([string]$robot.navigation.active_command_id)) {
            throw "An unexpected active command appeared between monitored goals."
        }

        if ($stopwatch.Elapsed.TotalSeconds -ge $nextGoalSec) {
            $front = Get-FrontClearance
            $yaw = [double]$robot.navigation.current.yaw
            $targetX = [double]$robot.navigation.current.x
            $targetY = [double]$robot.navigation.current.y
            $stationaryGoal = $front -lt $FrontClearanceM
            if (-not $stationaryGoal) {
                $targetX += $GoalOffsetM * [math]::Cos($yaw)
                $targetY += $GoalOffsetM * [math]::Sin($yaw)
            }

            $result = & $monitorScript `
                -BaseUrl $BaseUrl `
                -RobotId $RobotId `
                -X $targetX `
                -Y $targetY `
                -Yaw $yaw `
                -TimeoutSec 45
            $goalCount++
            [pscustomobject]@{
                Kind = "GOAL"
                Sequence = $goalCount
                BaselineElapsedSec = [math]::Round($stopwatch.Elapsed.TotalSeconds, 3)
                FrontClearanceM = [math]::Round($front, 3)
                StationaryGoal = $stationaryGoal
                Result = $result
            }
            $nextGoalSec = $stopwatch.Elapsed.TotalSeconds + $GoalIntervalSec
        }

        Start-Sleep -Seconds 1
    }

    $untilEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    Set-EmergencyStop
    Start-Sleep -Seconds 2
    $final = Get-RobotSnapshot
    [pscustomobject]@{
        Kind = "SUMMARY"
        SinceEpoch = $SinceEpoch
        UntilEpoch = $untilEpoch
        RangeSec = $untilEpoch - $SinceEpoch
        Goals = $goalCount
        MaxIdleLinearMps = [math]::Round($maxIdleLinear, 6)
        MaxIdleAngularRadps = [math]::Round($maxIdleAngular, 6)
        MinimumScanM = [math]::Round($minimumScan, 3)
        FinalState = [string]$final.navigation.state
        ActiveCommandId = [string]$final.navigation.active_command_id
        EstopActive = [bool]$final.safety.estop_active
        MotionArmed = [bool]$final.safety.motion_armed
    }
}
catch {
    try {
        Set-EmergencyStop
    }
    catch {
        Write-Warning "Failed to engage e-stop after collection error: $($_.Exception.Message)"
    }
    throw
}
