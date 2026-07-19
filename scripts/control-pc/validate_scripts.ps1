#Requires -Version 5.1

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$parseFailures = @()

Get-ChildItem -LiteralPath (Join-Path $repoRoot "scripts\control-pc") -Filter "*.ps1" |
    ForEach-Object {
        $tokens = $null
        $errors = $null
        [System.Management.Automation.Language.Parser]::ParseFile(
            $_.FullName,
            [ref]$tokens,
            [ref]$errors
        ) | Out-Null
        foreach ($parseError in $errors) {
            $parseFailures += "$($_.Name):$($parseError.Extent.StartLineNumber): $($parseError.Message)"
        }
    }

if ($parseFailures.Count -gt 0) {
    $parseFailures | ForEach-Object { Write-Error $_ }
    throw "PowerShell parser found $($parseFailures.Count) error(s)."
}

Write-Host "CONTROL_PC_POWERSHELL_VALIDATION_OK"
