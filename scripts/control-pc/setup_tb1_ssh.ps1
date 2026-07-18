#Requires -Version 5.1

[CmdletBinding()]
param(
    [string]$RobotAddress = "",
    [string]$RobotUser = "dcu",
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

Write-Host "TB1 will request the dcu account password once to register the key."
$installArgs = @(
    "-o", "BatchMode=no",
    "-o", "ConnectTimeout=15",
    "-o", "LogLevel=QUIET",
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "PubkeyAuthentication=no",
    "-o", "PreferredAuthentications=keyboard-interactive,password"
)
$remoteInstall = @'
set -eu
umask 077
mkdir -p "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
while IFS= read -r key; do
  if ! grep -qxF -- "$key" "$HOME/.ssh/authorized_keys"; then
    printf '%s\n' "$key" >>"$HOME/.ssh/authorized_keys"
  fi
done
chmod 700 "$HOME/.ssh"
chmod 600 "$HOME/.ssh/authorized_keys"
'@
Get-Content -LiteralPath $publicKeyFile -Raw |
    & $sshExe @installArgs $target $remoteInstall
if ($LASTEXITCODE -ne 0) {
    throw "TB1 rejected SSH key registration."
}

& $sshExe @batchArgs $target "printf TB1_SSH_AUTH_OK"
if ($LASTEXITCODE -ne 0) {
    throw "The dedicated key was copied but non-interactive SSH still fails."
}

Write-Host "`nTB1_SSH_SETUP_OK target=$target identity=$IdentityFile"
