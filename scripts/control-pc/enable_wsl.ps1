#Requires -Version 5.1
#Requires -RunAsAdministrator

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$outputDir = Join-Path $repoRoot "output"
$logPath = Join-Path $outputDir "control-pc-windows-stage.log"
$markerPath = Join-Path $outputDir "control-pc-windows-stage.txt"
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

Start-Transcript -Path $logPath -Force | Out-Null
try {
    $processor = Get-CimInstance Win32_Processor | Select-Object -First 1
    if (-not $processor.VirtualizationFirmwareEnabled) {
        throw "Firmware virtualization is disabled. Enable SVM/AMD-V in BIOS first."
    }

    foreach ($featureName in @(
        "Microsoft-Windows-Subsystem-Linux",
        "VirtualMachinePlatform"
    )) {
        $feature = Get-WindowsOptionalFeature -Online -FeatureName $featureName
        if ($feature.State -ne "Enabled") {
            Enable-WindowsOptionalFeature `
                -Online `
                -FeatureName $featureName `
                -All `
                -NoRestart | Out-Null
        }
    }

    $winget = (Get-Command winget.exe -ErrorAction Stop).Source
    foreach ($packageId in @(
        "Microsoft.WSL",
        "Canonical.Ubuntu.2204",
        "OpenJS.NodeJS.LTS"
    )) {
        & $winget list --exact --id $packageId `
            --accept-source-agreements `
            --disable-interactivity | Out-Null
        if ($LASTEXITCODE -ne 0) {
            & $winget install --exact --id $packageId --source winget `
                --silent `
                --accept-package-agreements `
                --accept-source-agreements `
                --disable-interactivity
            if ($LASTEXITCODE -ne 0) {
                throw "winget failed to install $packageId (exit $LASTEXITCODE)."
            }
        }
    }

    $result = @(
        "CONTROL_PC_WINDOWS_STAGE_OK",
        "VirtualizationFirmwareEnabled=True",
        "Microsoft-Windows-Subsystem-Linux=Enabled",
        "VirtualMachinePlatform=Enabled",
        "RebootRequired=True",
        "Next=powershell -ExecutionPolicy Bypass -File scripts/control-pc/bootstrap_wsl.ps1"
    )
    Set-Content -LiteralPath $markerPath -Value $result -Encoding UTF8
    $result | ForEach-Object { Write-Host $_ }
}
finally {
    Stop-Transcript | Out-Null
}
