#Requires -Version 5.1

[CmdletBinding()]
param(
    [string]$RobotAddress = "",
    [string]$RobotUser = "dg",
    [string]$IdentityFile = (Join-Path $HOME ".ssh\id_ed25519_tb1"),
    [string]$Distro = "Ubuntu-22.04",
    [switch]$RequireRobot
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$linuxRepo = "/home/fleetops/turtlebot-fleet-ops"
$failures = 0
$runtimeMarker = Join-Path $repoRoot "output\control-pc-runtime.txt"
$readyMarker = Join-Path $repoRoot "output\control-pc-ready.txt"

if ([string]::IsNullOrWhiteSpace($RobotAddress)) {
    if (Test-Path -LiteralPath $readyMarker) {
        $addressLine = Get-Content -LiteralPath $readyMarker |
            Where-Object { $_ -like "RobotAddress=*" } |
            Select-Object -First 1
        if ($null -ne $addressLine) {
            $RobotAddress = ($addressLine -split "=", 2)[1]
        }
    }
    if ([string]::IsNullOrWhiteSpace($RobotAddress)) {
        $RobotAddress = "tb1"
    }
}

function Write-Pass([string]$Message) { Write-Host "PASS: $Message" }
function Write-Fail([string]$Message) { Write-Host "FAIL: $Message" -ForegroundColor Red; $script:failures++ }
function Write-Warn([string]$Message) { Write-Host "WARN: $Message" -ForegroundColor Yellow }
function Test-TcpPort {
    param(
        [Parameter(Mandatory = $true)][string]$Address,
        [Parameter(Mandatory = $true)][int]$Port,
        [int]$TimeoutMilliseconds = 2000
    )

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $connect = $client.BeginConnect($Address, $Port, $null, $null)
        if (-not $connect.AsyncWaitHandle.WaitOne($TimeoutMilliseconds, $false)) {
            return $false
        }
        $client.EndConnect($connect)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Close()
    }
}

$robotSubnetPattern = $null
if ($RobotAddress -match '^(\d{1,3}\.\d{1,3}\.\d{1,3})\.\d{1,3}$') {
    $robotSubnetPattern = "$($Matches[1]).*"
}
$adapterAddress = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
        $_.IPAddress -notlike "127.*" -and
        $_.IPAddress -notlike "169.254.*" -and
        ($null -eq $robotSubnetPattern -or $_.IPAddress -like $robotSubnetPattern)
    } |
    Select-Object -First 1
if ($null -ne $adapterAddress) {
    Write-Pass "control LAN address $($adapterAddress.IPAddress)"
}
else {
    Write-Fail "no active Windows IPv4 address in the TB1 LAN"
}

$keepAliveProcess = $null
if (Test-Path -LiteralPath $runtimeMarker) {
    $processIdLine = Get-Content -LiteralPath $runtimeMarker |
        Where-Object { $_ -like "KeepAliveProcessId=*" } |
        Select-Object -First 1
    $processStartLine = Get-Content -LiteralPath $runtimeMarker |
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
if ($null -ne $keepAliveProcess) {
    Write-Pass "WSL control-stack keepalive process $($keepAliveProcess.Id)"
}
else {
    Write-Fail "WSL control-stack keepalive process is not running"
}

try {
    $gatewayHealth = Invoke-RestMethod `
        -Uri "http://127.0.0.1:8000/api/health" `
        -TimeoutSec 5
    if ($gatewayHealth.status -eq "ok") {
        Write-Pass "Fleet Gateway health endpoint"
    }
    else {
        Write-Fail "Fleet Gateway returned an unexpected health response"
    }
}
catch {
    Write-Fail "Fleet Gateway health endpoint is unavailable"
}

$sshReady = Test-TcpPort -Address $RobotAddress -Port 22
$zenohReady = Test-TcpPort -Address $RobotAddress -Port 7447
if ($sshReady) {
    Write-Pass "TB1 SSH $RobotAddress`:22"
    if (Test-Path -LiteralPath $IdentityFile) {
        $sshResult = & "$env:SystemRoot\System32\OpenSSH\ssh.exe" `
            -o BatchMode=yes `
            -o ConnectTimeout=8 `
            -o LogLevel=QUIET `
            -o StrictHostKeyChecking=accept-new `
            -o IdentitiesOnly=yes `
            -i $IdentityFile `
            "$RobotUser@$RobotAddress" `
            "printf TB1_SSH_AUTH_OK" 2>$null
        if ($LASTEXITCODE -eq 0 -and $sshResult -eq "TB1_SSH_AUTH_OK") {
            Write-Pass "TB1 non-interactive SSH authentication"
        }
        elseif ($RequireRobot) {
            Write-Fail "TB1 SSH key is not authorized; run setup_tb1_ssh.ps1 once"
        }
        else {
            Write-Warn "TB1 SSH port is open but key authentication is not ready"
        }
    }
    elseif ($RequireRobot) {
        Write-Fail "dedicated TB1 SSH key is missing; run setup_tb1_ssh.ps1"
    }
    else {
        Write-Warn "dedicated TB1 SSH key is not generated"
    }
}
elseif ($RequireRobot) { Write-Fail "TB1 SSH is unreachable" }
else { Write-Warn "TB1 SSH is offline; expected until the robot is connected" }
if ($zenohReady) { Write-Pass "TB1 Zenoh $RobotAddress`:7447" }
elseif ($RequireRobot) { Write-Fail "TB1 Zenoh is unreachable" }
else { Write-Warn "TB1 Zenoh is offline; expected until the robot is connected" }

& "$env:SystemRoot\System32\wsl.exe" -d $Distro -u fleetops -- bash -lc `
    "cd '$linuxRepo' && ROBOT_ADDRESS='$RobotAddress' bash scripts/control-pc/preflight_control_pc.sh"
if ($LASTEXITCODE -ne 0) {
    Write-Fail "WSL control stack preflight"
}
else {
    Write-Pass "WSL control stack preflight"
}

if ($failures -gt 0) {
    throw "TB1 connection preflight failed: $failures failure(s)."
}

Write-Host "TB1_CONNECTION_PREFLIGHT_OK robot=$RobotAddress require_robot=$RequireRobot"
