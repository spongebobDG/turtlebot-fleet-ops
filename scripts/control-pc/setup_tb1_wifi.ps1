#Requires -Version 5.1

[CmdletBinding()]
param(
    [string]$Ssid = "",
    [string]$RobotAddress = "",
    [string]$RobotUser = "dg",
    [string]$IdentityFile = (Join-Path $HOME ".ssh\id_ed25519_tb1"),
    [string]$Distro = "Ubuntu-22.04",
    [string]$LinuxUser = "fleetops"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$readyMarker = Join-Path $repoRoot "output\control-pc-ready.txt"
$sshExe = Join-Path $env:SystemRoot "System32\OpenSSH\ssh.exe"
$wslExe = Join-Path $env:SystemRoot "System32\wsl.exe"

foreach ($requiredPath in @($readyMarker, $sshExe, $wslExe, $IdentityFile)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required path is missing: $requiredPath"
    }
}

if ([string]::IsNullOrWhiteSpace($RobotAddress)) {
    $addressLine = Get-Content -LiteralPath $readyMarker |
        Where-Object { $_ -like "RobotAddress=*" } |
        Select-Object -First 1
    if ($null -ne $addressLine) {
        $RobotAddress = ($addressLine -split "=", 2)[1]
    }
}
if ([string]::IsNullOrWhiteSpace($RobotAddress)) {
    throw "The current wired TB1 address is missing from $readyMarker"
}

if ([string]::IsNullOrWhiteSpace($Ssid)) {
    $Ssid = Read-Host "TB1 Wi-Fi SSID"
}
if ([string]::IsNullOrWhiteSpace($Ssid)) {
    throw "The Wi-Fi SSID must not be empty."
}

$securePassword = Read-Host "TB1 Wi-Fi password (input is hidden)" -AsSecureString
$passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
    if ([string]::IsNullOrEmpty($plainPassword)) {
        throw "The Wi-Fi password must not be empty."
    }

    $ssidPayload = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Ssid))
    $passwordPayload = [Convert]::ToBase64String(
        [Text.Encoding]::UTF8.GetBytes($plainPassword)
    )
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
    $plainPassword = $null
    $securePassword.Dispose()
}

$remoteScript = @"
set -euo pipefail
set +x

target=/etc/netplan/60-turtlebot-fleet-ops-wifi.yaml
temporary=`$(mktemp)
backup=`$(mktemp)
had_previous=false

if ! sudo -n true >/dev/null 2>&1; then
  echo 'ERROR: passwordless sudo is required on TB1.' >&2
  exit 1
fi
trap 'rm -f "`${temporary}"; sudo -n rm -f "`${backup}"' EXIT

SSID_PAYLOAD='$ssidPayload' PASSWORD_PAYLOAD='$passwordPayload' python3 - "`${temporary}" <<'PY'
import base64
import json
import os
import pathlib
import sys

ssid = base64.b64decode(os.environ["SSID_PAYLOAD"]).decode("utf-8")
password = base64.b64decode(os.environ["PASSWORD_PAYLOAD"]).decode("utf-8")
content = "\n".join(
    [
        "network:",
        "  version: 2",
        "  wifis:",
        "    wlan0:",
        "      dhcp4: true",
        "      optional: true",
        "      access-points:",
        f"        {json.dumps(ssid, ensure_ascii=False)}:",
        f"          password: {json.dumps(password, ensure_ascii=False)}",
        "",
    ]
)
pathlib.Path(sys.argv[1]).write_text(content, encoding="utf-8")
PY

if sudo test -f "`${target}"; then
  sudo cp -a "`${target}" "`${backup}"
  had_previous=true
fi
sudo install -o root -g root -m 0600 "`${temporary}" "`${target}"

if ! sudo netplan generate; then
  if [[ "`${had_previous}" == true ]]; then
    sudo install -o root -g root -m 0600 "`${backup}" "`${target}"
  else
    sudo rm -f "`${target}"
  fi
  sudo netplan generate || true
  echo 'ERROR: netplan rejected the Wi-Fi configuration.' >&2
  exit 1
fi

sudo netplan apply
wifi_address=''
for _ in `$(seq 1 45); do
  wifi_address=`$(ip -4 -o address show wlan0 scope global 2>/dev/null | awk '{split(`$4, address, "/"); print address[1]; exit}')
  if [[ -n "`${wifi_address}" ]]; then
    break
  fi
  sleep 1
done

if [[ -z "`${wifi_address}" ]]; then
  echo 'ERROR: wlan0 did not receive an IPv4 address within 45 seconds.' >&2
  exit 1
fi

printf 'TB1_WIFI_READY address=%s\n' "`${wifi_address}"
"@

$sshArgs = @(
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=8",
    "-o", "LogLevel=QUIET",
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "IdentitiesOnly=yes",
    "-i", $IdentityFile
)
$target = "$RobotUser@$RobotAddress"
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    $remoteOutput = $remoteScript |
        & $sshExe @sshArgs $target "tr -d '\r' | bash" 2>&1
    $remoteExit = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
    $remoteScript = $null
    $ssidPayload = $null
    $passwordPayload = $null
}
$remoteOutput | ForEach-Object { Write-Host $_ }
if ($remoteExit -ne 0) {
    throw "TB1 Wi-Fi configuration failed. Keep the Ethernet cable connected."
}

$readyLine = $remoteOutput |
    Where-Object { $_ -match '^TB1_WIFI_READY address=(\d{1,3}(?:\.\d{1,3}){3})$' } |
    Select-Object -Last 1
if ($null -eq $readyLine) {
    throw "TB1 did not report a Wi-Fi IPv4 address. Keep the Ethernet cable connected."
}
$wifiAddress = ($readyLine -split "=", 2)[1]

$probeResult = & $sshExe @sshArgs "$RobotUser@$wifiAddress" "printf TB1_WIFI_SSH_OK" 2>$null
if ($LASTEXITCODE -ne 0 -or $probeResult -ne "TB1_WIFI_SSH_OK") {
    throw "Wi-Fi received an address but SSH verification failed. Keep Ethernet connected."
}
Write-Host "PASS: TB1 SSH is reachable through Wi-Fi"

# Long-running CycloneDDS participants retain the interface selected at startup.
# Rebind the fail-closed IDLE stack before the Ethernet link is removed.
$rebindCommand = "set -e; " +
    "if systemctl --user is-active --quiet tb1-mapping.service || " +
    "systemctl --user is-active --quiet tb1-navigation.service; then " +
    "echo 'A motion profile is active; refusing network rebind.' >&2; exit 1; fi; " +
    "systemctl --user stop tb1-zenoh-bridge.service tb1-robot-agent.service " +
    "tb1-safety-watchdog.service tb1-bringup.service; sleep 2; " +
    "systemctl --user start tb1-bringup.service; sleep 3; " +
    "systemctl --user start tb1-safety-watchdog.service tb1-robot-agent.service " +
    "tb1-zenoh-bridge.service"
& $sshExe @sshArgs "$RobotUser@$wifiAddress" $rebindCommand
if ($LASTEXITCODE -ne 0) {
    throw "Wi-Fi works, but the IDLE ROS stack could not rebind to it. Keep Ethernet connected."
}
Write-Host "PASS: TB1 IDLE ROS stack rebound after the interface change"

$markerLines = Get-Content -LiteralPath $readyMarker
$updatedAddress = $false
$markerLines = $markerLines | ForEach-Object {
    if ($_ -like "RobotAddress=*") {
        $updatedAddress = $true
        "RobotAddress=$wifiAddress"
    }
    else {
        $_
    }
}
if (-not $updatedAddress) {
    $markerLines += "RobotAddress=$wifiAddress"
}
Set-Content -LiteralPath $readyMarker -Value $markerLines -Encoding UTF8

$controlConfig = "/home/$LinuxUser/.config/turtlebot-fleet-ops/control.env"
$controlCommand = "set -e; " +
    "sed -i -E 's/^ROBOT_ADDRESS=.*/ROBOT_ADDRESS=$wifiAddress/' '$controlConfig'; " +
    "chmod 0600 '$controlConfig'; " +
    "systemctl --user restart fleet-control-zenoh.service fleet-gateway.service"
& $wslExe -d $Distro -u $LinuxUser -- bash -lc $controlCommand
if ($LASTEXITCODE -ne 0) {
    throw "Wi-Fi works, but the WSL control services could not be switched to its address."
}

$gatewayOnline = $false
foreach ($attempt in 1..30) {
    try {
        $robots = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/robots" -TimeoutSec 2
        $tb1 = $robots.robots | Where-Object { $_.robot_id -eq "tb1" } | Select-Object -First 1
        if ($null -ne $tb1 -and $tb1.online) {
            $gatewayOnline = $true
            break
        }
    }
    catch {
        # The Gateway may briefly restart while its robot endpoint changes.
    }
    Start-Sleep -Seconds 1
}
if (-not $gatewayOnline) {
    throw "Wi-Fi SSH works, but Gateway did not observe TB1. Keep Ethernet connected."
}

Write-Host "PASS: Gateway observes TB1 through the Wi-Fi endpoint"
Write-Host "TB1_WIFI_SETUP_OK address=$wifiAddress"
Write-Host "You may now unplug Ethernet, wait 10 seconds, and run test_tb1_connection.ps1 -RequireRobot."
