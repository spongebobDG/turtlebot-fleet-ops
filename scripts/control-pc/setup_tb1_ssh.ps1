#Requires -Version 5.1

[CmdletBinding()]
param(
    [string]$RobotAddress = "",
    [string]$RobotUser = "dg",
    [string]$IdentityFile = (Join-Path $HOME ".ssh\id_ed25519_tb1"),
    [switch]$GenerateOnly
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$readyMarker = Join-Path $repoRoot "output\control-pc-ready.txt"
$sshExe = Join-Path $env:SystemRoot "System32\OpenSSH\ssh.exe"
if (-not (Test-Path -LiteralPath $sshExe)) {
    throw "Windows OpenSSH client is missing: $sshExe"
}
$sshKeygenExe = (Get-Command ssh-keygen.exe -ErrorAction Stop).Source

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

$identityDirectory = Split-Path -Parent $IdentityFile
New-Item -ItemType Directory -Force -Path $identityDirectory | Out-Null
if (-not (Test-Path -LiteralPath $IdentityFile)) {
    & $sshKeygenExe `
        -q `
        -t ed25519 `
        -a 100 `
        -f $IdentityFile `
        -N '""' `
        -C "turtlebot-fleet-ops@$env:COMPUTERNAME"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not generate the dedicated TB1 SSH key."
    }
    Write-Host "PASS: generated dedicated key $IdentityFile"
}
else {
    Write-Host "PASS: dedicated key already exists at $IdentityFile"
}

$publicKeyFile = "$IdentityFile.pub"
if (-not (Test-Path -LiteralPath $publicKeyFile)) {
    throw "The public key is missing: $publicKeyFile"
}

if ($GenerateOnly) {
    Write-Host "TB1_SSH_KEY_READY identity=$IdentityFile registration=pending"
    exit 0
}

$target = "$RobotUser@$RobotAddress"
$batchArgs = @(
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=8",
    "-o", "LogLevel=QUIET",
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "IdentitiesOnly=yes",
    "-i", $IdentityFile
)
& $sshExe @batchArgs $target "printf TB1_SSH_AUTH_OK"
if ($LASTEXITCODE -eq 0) {
    Write-Host "`nPASS: TB1 already accepts the dedicated key"
    Write-Host "TB1_SSH_SETUP_OK target=$target identity=$IdentityFile"
    exit 0
}

Write-Host "TB1 will request the $RobotUser account password once to register the key."
$installArgs = @(
    "-o", "BatchMode=no",
    "-o", "ConnectTimeout=15",
    "-o", "LogLevel=QUIET",
    "-o", "NumberOfPasswordPrompts=1",
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "PubkeyAuthentication=no",
    "-o", "PreferredAuthentications=keyboard-interactive,password"
)
$publicKey = (Get-Content -LiteralPath $publicKeyFile -Raw).Trim()
if ($publicKey -notmatch '^ssh-ed25519 [A-Za-z0-9+/=]+(?: [^\r\n]+)?$') {
    throw "The dedicated TB1 public key has an unexpected format."
}
$publicKeyPayload = [Convert]::ToBase64String(
    [Text.Encoding]::UTF8.GetBytes("$publicKey`n")
)
$remoteInstall = "set -eu; umask 077; mkdir -p .ssh; " +
    "touch .ssh/authorized_keys; " +
    "printf %s $publicKeyPayload | base64 -d >.ssh/id_ed25519_tb1.pub.pending; " +
    "grep -qxF -f .ssh/id_ed25519_tb1.pub.pending .ssh/authorized_keys || " +
    "cat .ssh/id_ed25519_tb1.pub.pending >>.ssh/authorized_keys; " +
    "rm -f .ssh/id_ed25519_tb1.pub.pending; " +
    "chmod 700 .ssh; chmod 600 .ssh/authorized_keys"
& $sshExe @installArgs $target $remoteInstall
if ($LASTEXITCODE -ne 0) {
    throw "TB1 rejected SSH key registration."
}

& $sshExe @batchArgs $target "printf TB1_SSH_AUTH_OK"
if ($LASTEXITCODE -ne 0) {
    throw "The dedicated key was copied but non-interactive SSH still fails."
}

Write-Host "`nTB1_SSH_SETUP_OK target=$target identity=$IdentityFile"
