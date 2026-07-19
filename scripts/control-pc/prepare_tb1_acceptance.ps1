#Requires -Version 5.1

[CmdletBinding()]
param(
    [ValidateSet("Audit", "Deploy", "Collect")]
    [string]$Action = "Collect",
    [string]$RobotAddress = "",
    [string]$RobotUser = "dg",
    [string]$IdentityFile = (Join-Path $HOME ".ssh\id_ed25519_tb1"),
    [string]$Branch = "",
    [switch]$RequireMap
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$readyMarker = Join-Path $repoRoot "output\control-pc-ready.txt"
$connectionScript = Join-Path $PSScriptRoot "test_tb1_connection.ps1"
$remotePreflight = Join-Path $repoRoot "scripts\tb1\preflight_acceptance.sh"
$remoteEvidence = Join-Path $repoRoot "scripts\tb1\collect_acceptance_evidence.sh"
$sshExe = Join-Path $env:SystemRoot "System32\OpenSSH\ssh.exe"
if (-not (Test-Path -LiteralPath $sshExe)) {
    throw "Windows OpenSSH client is missing: $sshExe"
}

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

if ([string]::IsNullOrWhiteSpace($Branch)) {
    $Branch = (& git -C $repoRoot branch --show-current).Trim()
}
if ($Branch -notmatch '^[A-Za-z0-9._/-]+$') {
    throw "Unsafe Git branch name: $Branch"
}
if (-not (Test-Path -LiteralPath $IdentityFile)) {
    throw "Dedicated TB1 key is missing. Run setup_tb1_ssh.ps1 -GenerateOnly first."
}

$target = "$RobotUser@$RobotAddress"
$sshArgs = @(
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=8",
    "-o", "LogLevel=QUIET",
    "-o", "ServerAliveInterval=5",
    "-o", "ServerAliveCountMax=2",
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "IdentitiesOnly=yes",
    "-i", $IdentityFile
)

function Invoke-ConnectionCheck {
    & $connectionScript `
        -RobotAddress $RobotAddress `
        -RobotUser $RobotUser `
        -IdentityFile $IdentityFile `
        -RequireRobot
}

function Invoke-Utf8RemoteScript {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$RemoteCommand
    )

    # Windows PowerShell 5.1 can prepend a BOM when text is piped to a native
    # process. Bash then treats the shebang as a command instead of a comment.
    $scriptText = (Get-Content -LiteralPath $Path -Raw).TrimStart([char]0xFEFF)
    $previousOutputEncoding = $OutputEncoding
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $OutputEncoding = New-Object System.Text.UTF8Encoding($false)
        $ErrorActionPreference = "Continue"
        $bomFilter = "python3 -c 'import sys; data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data[3:] if data.startswith(bytes((239,187,191))) else data)'"
        $normalizedRemoteCommand = "$bomFilter | $RemoteCommand"
        $output = $scriptText |
            & $sshExe @sshArgs $target $normalizedRemoteCommand 2>&1
        $remoteExit = $LASTEXITCODE
    }
    finally {
        $OutputEncoding = $previousOutputEncoding
        $ErrorActionPreference = $previousErrorActionPreference
    }

    return [pscustomobject]@{
        Output = $output
        ExitCode = $remoteExit
    }
}

function Invoke-RemoteScript {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string[]]$Arguments = @()
    )

    # Windows PowerShell may add CRLF while piping text to a native process.
    # Normalize on the robot before Bash parses the streamed script.
    $remoteCommand = "tr -d '\r' | bash -s --"
    if ($Arguments.Count -gt 0) {
        $remoteCommand += " " + ($Arguments -join " ")
    }
    $result = Invoke-Utf8RemoteScript -Path $Path -RemoteCommand $remoteCommand
    $result.Output | Write-Output
    if ($result.ExitCode -ne 0) {
        throw "Remote script failed: $Path"
    }
}

function Invoke-RemoteAudit {
    $arguments = @()
    if ($RequireMap) {
        $arguments += "--require-map"
    }
    Invoke-RemoteScript -Path $remotePreflight -Arguments $arguments
}

function Save-Evidence {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $evidenceDir = Join-Path $repoRoot "output\tb1-acceptance\$timestamp"
    New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null

    $hostMetadata = @(
        "Timestamp=$([DateTimeOffset]::Now.ToString('o'))",
        "Robot=$target",
        "Action=$Action",
        "Branch=$Branch",
        "HostCommit=$((& git -C $repoRoot rev-parse HEAD).Trim())",
        "Gateway=http://127.0.0.1:8000"
    )
    Set-Content `
        -LiteralPath (Join-Path $evidenceDir "manifest.txt") `
        -Value $hostMetadata `
        -Encoding UTF8

    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 5 |
            ConvertTo-Json -Depth 10 |
            Set-Content `
                -LiteralPath (Join-Path $evidenceDir "gateway-health.json") `
                -Encoding UTF8
        Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/robots" -TimeoutSec 5 |
            ConvertTo-Json -Depth 20 |
            Set-Content `
                -LiteralPath (Join-Path $evidenceDir "gateway-robots.json") `
                -Encoding UTF8
    }
    catch {
        $_ | Out-String | Set-Content `
            -LiteralPath (Join-Path $evidenceDir "gateway-api-error.txt") `
            -Encoding UTF8
    }

    $remoteResult = Invoke-Utf8RemoteScript `
        -Path $remoteEvidence `
        -RemoteCommand "tr -d '\r' | bash -s --"
    $remoteResult.Output |
        Tee-Object -FilePath (Join-Path $evidenceDir "tb1-baseline.txt")
    if ($remoteResult.ExitCode -ne 0) {
        throw "TB1 evidence capture failed with exit code $($remoteResult.ExitCode)."
    }

    Get-ChildItem -LiteralPath $evidenceDir -File |
        Get-FileHash -Algorithm SHA256 |
        ForEach-Object { "$($_.Hash)  $($_.Path | Split-Path -Leaf)" } |
        Set-Content `
            -LiteralPath (Join-Path $evidenceDir "sha256.txt") `
            -Encoding ASCII

    Write-Host "TB1_ACCEPTANCE_EVIDENCE_OK directory=$evidenceDir"
}

Invoke-ConnectionCheck

if ($Action -eq "Deploy") {
    if (-not [string]::IsNullOrWhiteSpace((& git -C $repoRoot status --porcelain))) {
        throw "Refusing deployment from a dirty control-PC repository."
    }
    $hostCommit = (& git -C $repoRoot rev-parse HEAD).Trim()
    $remoteUpdate = @'
set -euo pipefail
repo="$HOME/turtlebot-fleet-ops"
if [[ ! -d "$repo/.git" ]]; then
  git clone --branch '__BRANCH__' --single-branch \
    'https://github.com/spongebobDG/turtlebot-fleet-ops.git' "$repo"
else
  cd "$repo"
  if [[ -n "$(git status --porcelain)" ]]; then
    echo "ERROR: refusing to overwrite TB1 local changes." >&2
    git status --short >&2
    exit 20
  fi
  git fetch --prune origin '__BRANCH__'
  git checkout -B '__BRANCH__' FETCH_HEAD
fi
git -C "$repo" rev-parse HEAD
'@
    $remoteUpdate = $remoteUpdate.Replace('__BRANCH__', $Branch)
    $remoteCommitOutput = & $sshExe @sshArgs $target $remoteUpdate
    if ($LASTEXITCODE -ne 0) {
        throw "Could not synchronize the TB1 repository."
    }
    $remoteCommit = ($remoteCommitOutput | Select-Object -Last 1).Trim()
    if ($remoteCommit -ne $hostCommit) {
        throw "TB1 fetched $remoteCommit but the control PC is at $hostCommit. Push first."
    }

    $deployArgs = $sshArgs + @("-tt")
    & $sshExe @deployArgs $target `
        "cd ~/turtlebot-fleet-ops && bash scripts/tb1/deploy_acceptance.sh"
    if ($LASTEXITCODE -ne 0) {
        throw "TB1 deployment failed; motion services were intentionally left stopped."
    }
}

Invoke-RemoteAudit
if ($Action -ne "Audit") {
    Save-Evidence
}

Write-Host "TB1_ACCEPTANCE_PREPARATION_OK action=$Action robot=$target"
