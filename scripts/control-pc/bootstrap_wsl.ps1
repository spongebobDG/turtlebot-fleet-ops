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
$logPath = Join-Path $outputDir "control-pc-wsl-bootstrap.log"
$markerPath = Join-Path $outputDir "control-pc-ready.txt"
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

if ($LinuxUser -notmatch '^[A-Za-z_][A-Za-z0-9_-]*$') {
    throw "Invalid WSL user name: $LinuxUser"
}

if ([string]::IsNullOrWhiteSpace($RobotAddress)) {
    if (Test-Path -LiteralPath $markerPath) {
        $addressLine = Get-Content -LiteralPath $markerPath |
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

function Invoke-Wsl {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & "$env:SystemRoot\System32\wsl.exe" @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "wsl.exe failed (exit $LASTEXITCODE): $($Arguments -join ' ')"
    }
}

function Convert-ToWslPath {
    param([Parameter(Mandatory = $true)][string]$WindowsPath)

    $fullPath = [System.IO.Path]::GetFullPath($WindowsPath)
    if ($fullPath -notmatch '^([A-Za-z]):\\(.*)$') {
        throw "Only drive-letter paths are supported: $fullPath"
    }
    $drive = $Matches[1].ToLowerInvariant()
    $tail = $Matches[2].Replace('\', '/')
    return "/mnt/$drive/$tail"
}

Start-Transcript -Path $logPath -Force | Out-Null
try {
    $node = Get-Command node.exe -ErrorAction Stop
    & $node.Source --check (Join-Path $repoRoot "control\fleet_gateway\web\app.js")
    if ($LASTEXITCODE -ne 0) {
        throw "Windows Node.js failed the fleet web syntax check."
    }
    & $node.Source --check (Join-Path $repoRoot "control\fleet_gateway\web\manual_keys.js")
    if ($LASTEXITCODE -ne 0) {
        throw "Windows Node.js failed the WASD helper syntax check."
    }

    & "$env:SystemRoot\System32\wsl.exe" --update --web-download
    if ($LASTEXITCODE -ne 0) {
        throw "WSL update failed. Confirm the Windows features were enabled and Windows was rebooted."
    }
    & "$env:SystemRoot\System32\wsl.exe" --set-default-version 2
    if ($LASTEXITCODE -ne 0) {
        throw "Could not set WSL 2 as the default version."
    }

    $distroList = (& "$env:SystemRoot\System32\wsl.exe" --list --quiet 2>$null) `
        -replace "`0", ""
    if ($distroList -notcontains $Distro) {
        $launcher = Get-Command ubuntu2204.exe -ErrorAction SilentlyContinue
        if ($null -eq $launcher) {
            $winget = (Get-Command winget.exe -ErrorAction Stop).Source
            & $winget install --exact --id Canonical.Ubuntu.2204 --source winget `
                --silent `
                --accept-package-agreements `
                --accept-source-agreements `
                --disable-interactivity
            if ($LASTEXITCODE -ne 0) {
                throw "Ubuntu 22.04 package installation failed."
            }
            $launcher = Get-Command ubuntu2204.exe -ErrorAction Stop
        }
        & $launcher.Source install --root
        if ($LASTEXITCODE -ne 0) {
            throw "Ubuntu 22.04 initialization failed."
        }
    }

    Invoke-Wsl -Arguments @(
        "-d", $Distro, "-u", "root", "--", "bash", "-lc",
        "set -e; id -u '$LinuxUser' >/dev/null 2>&1 || useradd -m -s /bin/bash '$LinuxUser'; apt-get update; apt-get install -y sudo; printf '%s ALL=(ALL) NOPASSWD:ALL\n' '$LinuxUser' >/etc/sudoers.d/$LinuxUser; chmod 0440 /etc/sudoers.d/$LinuxUser; printf '[boot]\nsystemd=true\n[user]\ndefault=$LinuxUser\n' >/etc/wsl.conf"
    )

    & "$env:SystemRoot\System32\wsl.exe" --shutdown
    Start-Sleep -Seconds 3

    $sourcePath = Convert-ToWslPath -WindowsPath $repoRoot
    $linuxRepo = "/home/$LinuxUser/turtlebot-fleet-ops"
    $copyCommand = "set -e; test '$linuxRepo' = '/home/$LinuxUser/turtlebot-fleet-ops'; rm -rf -- '$linuxRepo/build' '$linuxRepo/install' '$linuxRepo/log'; mkdir -p '$linuxRepo'; tar -C '$sourcePath' --exclude='./build' --exclude='./install' --exclude='./log' --exclude='./output' -cf - . | tar -C '$linuxRepo' -xf -; find '$linuxRepo' -type d -exec chmod 0755 {} +; find '$linuxRepo' -type f -exec chmod 0644 {} +; find '$linuxRepo/infra' '$linuxRepo/scripts' -type f -name '*.sh' -exec chmod 0755 {} +; chown -R '${LinuxUser}:${LinuxUser}' '$linuxRepo'"
    Invoke-Wsl -Arguments @("-d", $Distro, "-u", "root", "--", "bash", "-lc", $copyCommand)

    $bootstrapCommand = "cd '$linuxRepo' && ROBOT_ADDRESS='$RobotAddress' bash scripts/control-pc/bootstrap_control_pc.sh"
    Invoke-Wsl -Arguments @("-d", $Distro, "-u", $LinuxUser, "--", "bash", "-lc", $bootstrapCommand)

    $preflightCommand = "cd '$linuxRepo' && ROBOT_ADDRESS='$RobotAddress' bash scripts/control-pc/preflight_control_pc.sh"
    Invoke-Wsl -Arguments @("-d", $Distro, "-u", $LinuxUser, "--", "bash", "-lc", $preflightCommand)

    $runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    $startScript = Join-Path $repoRoot "scripts\control-pc\start_control_stack.ps1"
    $startCommand = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$startScript`""
    New-Item -Path $runKey -Force | Out-Null
    New-ItemProperty `
        -Path $runKey `
        -Name "TurtleBotFleetControlStack" `
        -Value $startCommand `
        -PropertyType String `
        -Force | Out-Null

    & powershell.exe `
        -NoProfile `
        -ExecutionPolicy Bypass `
        -File $startScript `
        -Distro $Distro `
        -LinuxUser $LinuxUser
    if ($LASTEXITCODE -ne 0) {
        throw "The persistent WSL control stack failed to start."
    }

    $result = @(
        "CONTROL_PC_READY",
        "Distro=$Distro",
        "LinuxUser=$LinuxUser",
        "RobotAddress=$RobotAddress",
        "Repo=$linuxRepo",
        "Dashboard=http://localhost:8000",
        "WindowsLogonAutostart=True",
        "ControlStackKeepAlive=True"
    )
    Set-Content -LiteralPath $markerPath -Value $result -Encoding UTF8
    $result | ForEach-Object { Write-Host $_ }
}
finally {
    Stop-Transcript | Out-Null
}
