[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ExperimentName,

    [ValidateRange(1, 3600)]
    [int]$DurationSec = 30,

    [ValidateRange(50, 5000)]
    [int]$IntervalMs = 100,

    [ValidateNotNullOrEmpty()]
    [string]$RobotId = "tb1",

    [ValidateNotNullOrEmpty()]
    [string]$GatewayUrl = "http://127.0.0.1:8000",

    [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"
$culture = [System.Globalization.CultureInfo]::InvariantCulture
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $repoRoot "artifacts\experiments"
}
$resolvedOutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
[System.IO.Directory]::CreateDirectory($resolvedOutputDirectory) | Out-Null

$safeName = $ExperimentName -replace "[^A-Za-z0-9._-]", "_"
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmss.fffZ")
$outputPath = Join-Path $resolvedOutputDirectory "$stamp-$safeName.csv"
$endpoint = "$($GatewayUrl.TrimEnd('/'))/api/robots/$RobotId"
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$writer = [System.IO.StreamWriter]::new($outputPath, $false, [Text.UTF8Encoding]::new($false))
$headerWritten = $false

Write-Output "TB1_EXPERIMENT_CSV=$outputPath"

try {
    while ($stopwatch.Elapsed.TotalSeconds -lt $DurationSec) {
        $capturedAt = (Get-Date).ToUniversalTime().ToString("o")
        $errorMessage = ""
        try {
            $status = Invoke-RestMethod -Uri $endpoint -TimeoutSec 2
        }
        catch {
            $status = $null
            $errorMessage = $_.Exception.Message
        }

        $row = [ordered]@{
            captured_at = $capturedAt
            elapsed_sec = $stopwatch.Elapsed.TotalSeconds.ToString("F3", $culture)
            experiment = $ExperimentName
            robot_id = $RobotId
            online = $status.online
            profile = $status.mapping.profile
            navigation_state = $status.navigation.state
            nav2_ready = $status.navigation.nav2_ready
            localization_ready = $status.navigation.localization_ready
            safety_mode = $status.safety.mode
            estop_active = $status.safety.estop_active
            motion_armed = $status.safety.motion_armed
            odom_x_m = $status.odom.x
            odom_y_m = $status.odom.y
            odom_yaw_rad = $status.odom.yaw
            linear_velocity_mps = $status.odom.linear_velocity
            angular_velocity_radps = $status.odom.angular_velocity
            scan_received = $status.scan.received
            scan_fresh = $status.scan.fresh
            scan_valid_points = $status.scan.valid_points
            scan_min_range_m = $status.scan.min_range
            battery_percent = $status.battery.percent
            battery_voltage_v = $status.battery.voltage
            wifi_signal_dbm = $status.wifi.signal_dbm
            cpu_percent = $status.system.cpu_percent
            memory_percent = $status.system.memory_percent
            fault_codes = (($status.fault_codes | ForEach-Object { [string]$_ }) -join "|")
            collection_error = $errorMessage
        }
        $csvLines = [pscustomobject]$row | ConvertTo-Csv -NoTypeInformation
        if (-not $headerWritten) {
            $writer.WriteLine($csvLines[0])
            $headerWritten = $true
        }
        $writer.WriteLine($csvLines[1])
        $writer.Flush()
        Start-Sleep -Milliseconds $IntervalMs
    }
}
finally {
    $writer.Dispose()
}

Write-Output "TB1_EXPERIMENT_CSV_COMPLETE=$outputPath"
