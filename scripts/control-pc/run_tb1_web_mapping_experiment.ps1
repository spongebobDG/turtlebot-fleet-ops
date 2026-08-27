[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ExperimentName,

    [ValidateSet("translate", "rotate")]
    [string]$Mode = "translate",

    [ValidateRange(0.01, 1.0)]
    [double]$Target = 0.05,

    [ValidateRange(0.01, 0.3)]
    [double]$Speed = 0.02,

    [ValidateRange(1, 60)]
    [int]$MotionTimeoutSec = 8,

    [ValidateRange(0.1, 5.0)]
    [double]$MinimumClearanceM = 0.30,

    [ValidateRange(0.0, 0.2)]
    [double]$StopMargin = 0.0,

    [ValidateRange(0.0, 3.0)]
    [double]$PredictionHorizonSec = 0.0,

    [ValidateRange(0.5, 1.0)]
    [double]$MinimumCompletionRatio = 0.9,

    [ValidateRange(0.0, 0.5)]
    [double]$MaximumOvershoot = 0.0,

    [ValidateNotNullOrEmpty()]
    [string]$RobotId = "tb1",

    [ValidateNotNullOrEmpty()]
    [string]$GatewayUrl = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$collector = Join-Path $PSScriptRoot "collect_tb1_experiment_csv.ps1"
$csvDurationSec = $MotionTimeoutSec + 18
$baseUrl = $GatewayUrl.TrimEnd("/")
$robotUrl = "$baseUrl/api/robots/$RobotId"
$sessionId = $null
$failure = $null
$commandSamples = 0
$controlProgress = 0.0
$result = $null

if ($PredictionHorizonSec -eq 0.0) {
    $PredictionHorizonSec = if ($Mode -eq "translate") { 0.8 } else { 0.5 }
}
if ($MaximumOvershoot -eq 0.0) {
    $MaximumOvershoot = if ($Mode -eq "translate") { 0.02 } else { 0.08 }
}
$controlTarget = [Math]::Max($Target - $StopMargin, $Target * 0.7)
$logger = Start-Job -ScriptBlock {
    param($script, $workingDirectory, $name, $duration)
    Set-Location -LiteralPath $workingDirectory
    & $script `
        -ExperimentName $name `
        -DurationSec $duration `
        -IntervalMs 100
} -ArgumentList $collector, $repoRoot, $ExperimentName, $csvDurationSec

function Invoke-GatewayJson {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Uri,
        [ValidateSet("Get", "Post", "Put", "Delete")]
        [string]$Method = "Get",
        [object]$Body = $null
    )
    $arguments = @{
        Uri = $Uri
        Method = $Method
        TimeoutSec = 10
    }
    if ($null -ne $Body) {
        $arguments.ContentType = "application/json"
        $arguments.Body = $Body | ConvertTo-Json -Compress
    }
    Invoke-RestMethod @arguments
}

function Get-WrappedYawDelta {
    param([double]$Current, [double]$Initial)
    $delta = $Current - $Initial
    while ($delta -gt [Math]::PI) { $delta -= 2.0 * [Math]::PI }
    while ($delta -lt -[Math]::PI) { $delta += 2.0 * [Math]::PI }
    $delta
}

Start-Sleep -Seconds 2
try {
    $robot = Invoke-GatewayJson -Uri $robotUrl
    if ($robot.mapping.profile -ne "MAPPING" -or $robot.mapping.transitioning) {
        throw "MAPPING profile is required and must be stable"
    }
    if (-not $robot.scan.fresh) {
        throw "scan is stale before the experiment"
    }
    if ([double]$robot.scan.min_range -lt $MinimumClearanceM) {
        throw "clearance is unsafe before the experiment: $($robot.scan.min_range)m"
    }

    Invoke-GatewayJson `
        -Uri "$robotUrl/estop" `
        -Method Post `
        -Body @{ engaged = $false } | Out-Null
    $armDeadline = (Get-Date).AddSeconds(8)
    do {
        Start-Sleep -Milliseconds 150
        $robot = Invoke-GatewayJson -Uri $robotUrl
    } until (
        ($robot.safety.motion_armed -and -not $robot.safety.estop_active) `
        -or (Get-Date) -gt $armDeadline
    )
    if (-not $robot.safety.motion_armed) {
        throw "watchdog did not arm after neutral input"
    }

    $startX = [double]$robot.odom.x
    $startY = [double]$robot.odom.y
    $startYaw = [double]$robot.odom.yaw
    $session = Invoke-GatewayJson `
        -Uri "$robotUrl/manual/sessions" `
        -Method Post `
        -Body @{ confirm_warnings = $false }
    $sessionId = [string]$session.session_id
    $motionDeadline = (Get-Date).AddSeconds($MotionTimeoutSec)

    while ($controlProgress -lt $controlTarget) {
        if ((Get-Date) -gt $motionDeadline) {
            throw "motion timed out at progress=$controlProgress"
        }
        $robot = Invoke-GatewayJson -Uri $robotUrl
        if (-not $robot.scan.fresh) {
            throw "scan became stale during motion"
        }
        if ([double]$robot.scan.min_range -lt $MinimumClearanceM) {
            throw "clearance dropped to $($robot.scan.min_range)m"
        }
        if ($robot.safety.estop_active -or -not $robot.safety.motion_armed) {
            throw "safety state dropped during motion"
        }
        if ($Mode -eq "translate") {
            $deltaX = [double]$robot.odom.x - $startX
            $deltaY = [double]$robot.odom.y - $startY
            $controlProgress = `
                $deltaX * [Math]::Cos($startYaw) `
                + $deltaY * [Math]::Sin($startYaw)
            $command = @{ linear_x = $Speed; angular_z = 0.0 }
            $measuredSpeed = [Math]::Abs(
                [double]$robot.odom.linear_velocity
            )
        }
        else {
            $controlProgress = Get-WrappedYawDelta `
                -Current ([double]$robot.odom.yaw) `
                -Initial $startYaw
            $command = @{ linear_x = 0.0; angular_z = $Speed }
            $measuredSpeed = [Math]::Abs(
                [double]$robot.odom.angular_velocity
            )
        }
        $predictionSpeed = [Math]::Min(
                [Math]::Max($measuredSpeed, $Speed * 0.2),
            $Speed
        )
        $predictedProgress = `
            $controlProgress + $predictionSpeed * $PredictionHorizonSec
        if ($predictedProgress -ge $controlTarget) { break }
        Invoke-GatewayJson `
            -Uri "$robotUrl/manual/sessions/$sessionId" `
            -Method Put `
            -Body $command | Out-Null
        $commandSamples += 1
        Start-Sleep -Milliseconds 80
    }

    Invoke-GatewayJson `
        -Uri "$robotUrl/manual/sessions/$sessionId" `
        -Method Put `
        -Body @{ linear_x = 0.0; angular_z = 0.0 } | Out-Null
    Invoke-GatewayJson `
        -Uri "$robotUrl/manual/sessions/$sessionId" `
        -Method Delete | Out-Null
    $sessionId = $null
}
catch {
    $failure = $_
}
finally {
    if ($sessionId) {
        try {
            Invoke-GatewayJson `
                -Uri "$robotUrl/manual/sessions/$sessionId" `
                -Method Delete | Out-Null
        }
        catch {
            if (-not $failure) { $failure = $_ }
        }
    }
    try {
        Invoke-GatewayJson `
            -Uri "$robotUrl/estop" `
            -Method Post `
            -Body @{ engaged = $true } | Out-Null
    }
    catch {
        if (-not $failure) { $failure = $_ }
    }
}

Start-Sleep -Milliseconds 800
try {
    $finalRobot = Invoke-GatewayJson -Uri $robotUrl
    $finalX = [double]$finalRobot.odom.x
    $finalY = [double]$finalRobot.odom.y
    $finalYaw = [double]$finalRobot.odom.yaw
    if ($Mode -eq "translate") {
        $finalProgress = `
            ($finalX - $startX) * [Math]::Cos($startYaw) `
            + ($finalY - $startY) * [Math]::Sin($startYaw)
    }
    else {
        $finalProgress = Get-WrappedYawDelta `
            -Current $finalYaw `
            -Initial $startYaw
    }
    $result = [ordered]@{
        experiment = $ExperimentName
        mode = $Mode
        target = $Target
        control_target = $controlTarget
        prediction_horizon_sec = $PredictionHorizonSec
        control_progress = $controlProgress
        final_progress = $finalProgress
        target_error = $finalProgress - $Target
        command_samples = $commandSamples
        minimum_range_m = [double]$finalRobot.scan.min_range
        estop_active = [bool]$finalRobot.safety.estop_active
        motion_armed = [bool]$finalRobot.safety.motion_armed
        fault_codes = @($finalRobot.fault_codes)
        passed = $false
    }
    if (-not $result.estop_active -or $result.motion_armed) {
        throw "final fail-closed state was not confirmed"
    }
    if ($result.fault_codes.Count -gt 0) {
        throw "active robot faults remained: $($result.fault_codes -join ',')"
    }
    $minimumProgress = $Target * $MinimumCompletionRatio
    $maximumProgress = $Target + $MaximumOvershoot
    if (
        $finalProgress -lt $minimumProgress `
        -or $finalProgress -gt $maximumProgress
    ) {
        throw (
            "final progress $finalProgress is outside acceptance range " +
            "[$minimumProgress, $maximumProgress]"
        )
    }
    $result["passed"] = $true
}
catch {
    if (-not $failure) { $failure = $_ }
}

Wait-Job $logger | Out-Null
Receive-Job $logger
Remove-Job $logger
if ($result) {
    Write-Output "TB1_MAPPING_RESULT=$($result | ConvertTo-Json -Compress)"
}
if ($failure) {
    throw $failure
}
