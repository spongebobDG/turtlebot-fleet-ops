#Requires -Version 5.1
#Requires -RunAsAdministrator

[CmdletBinding()]
param(
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $repoRoot "output\windows-time-sync.txt"
}
$outputDirectory = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null

function Invoke-W32Time {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $result = & "$env:SystemRoot\System32\w32tm.exe" @Arguments 2>&1
    $result | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) {
        throw "w32tm $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Get-WindowsTimeOffsetSec {
    $stripchart = & "$env:SystemRoot\System32\w32tm.exe" /stripchart /computer:time.google.com /dataonly /samples:3 2>&1
    $offsets = @(
        $stripchart |
            ForEach-Object { [regex]::Match($_.ToString(), "(?<offset>[+-]\d+[\.,]\d+)s") } |
            Where-Object { $_.Success } |
            ForEach-Object {
                [double]::Parse(
                    $_.Groups["offset"].Value.TrimEnd("s").Replace(",", "."),
                    [Globalization.CultureInfo]::InvariantCulture
                )
            }
    )
    if ($offsets.Count -eq 0) {
        throw "Windows Time offset query returned no usable NTP samples"
    }
    return [double]$offsets[-1]
}

$startedAt = [DateTimeOffset]::Now
Set-Service -Name W32Time -StartupType Automatic
Start-Service -Name W32Time
Invoke-W32Time -Arguments @(
    "/config",
    "/manualpeerlist:time.windows.com,0x8 time.nist.gov,0x8 time.google.com,0x8",
    "/syncfromflags:manual",
    "/reliable:no",
    "/update"
)
Restart-Service -Name W32Time -Force
Invoke-W32Time -Arguments @("/resync", "/rediscover")
Start-Sleep -Seconds 3

$offsetBeforeCorrectionSec = Get-WindowsTimeOffsetSec
if ([Math]::Abs($offsetBeforeCorrectionSec) -gt 0.2) {
    # W32Time slews offsets below MaxAllowedPhaseOffset. Zenoh rejects timestamps
    # beyond 500 ms, so force one immediate correction and then restore policy.
    $configPath = "HKLM:\SYSTEM\CurrentControlSet\Services\W32Time\Config"
    $originalMaxAllowedPhaseOffset =
        (Get-ItemProperty -LiteralPath $configPath -Name MaxAllowedPhaseOffset).MaxAllowedPhaseOffset
    try {
        Set-ItemProperty -LiteralPath $configPath -Name MaxAllowedPhaseOffset -Type DWord -Value 0
        Restart-Service -Name W32Time -Force
        Invoke-W32Time -Arguments @("/resync", "/rediscover")
        Start-Sleep -Seconds 3
    }
    finally {
        Set-ItemProperty -LiteralPath $configPath -Name MaxAllowedPhaseOffset -Type DWord `
            -Value $originalMaxAllowedPhaseOffset
        Invoke-W32Time -Arguments @("/config", "/update")
    }
}

$offsetAfterCorrectionSec = Get-WindowsTimeOffsetSec
if ([Math]::Abs($offsetAfterCorrectionSec) -gt 0.2) {
    throw "Windows Time offset remains $offsetAfterCorrectionSec seconds (required: <= 0.2 seconds)"
}

$source = (& "$env:SystemRoot\System32\w32tm.exe" /query /source 2>&1 |
    Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($source)) {
    throw "Windows Time source query failed"
}
if ($source -eq "Local CMOS Clock") {
    throw "Windows Time still uses Local CMOS Clock"
}
$status = (& "$env:SystemRoot\System32\w32tm.exe" /query /status 2>&1 |
    Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Windows Time status query failed"
}

@(
    "Timestamp=$([DateTimeOffset]::Now.ToString('o'))",
    "StartedAt=$($startedAt.ToString('o'))",
    "Source=$source",
    "OffsetBeforeCorrectionSec=$offsetBeforeCorrectionSec",
    "OffsetAfterCorrectionSec=$offsetAfterCorrectionSec",
    "Status:",
    $status,
    "WINDOWS_TIME_SYNC_OK"
) | Set-Content -LiteralPath $OutputPath -Encoding UTF8

Write-Host "WINDOWS_TIME_SYNC_OK source=$source output=$OutputPath"
