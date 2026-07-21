[CmdletBinding()]
param(
    [ValidateSet('menu', 'status', 'start', 'stop', 'restart', 'logs')]
    [string]$Action = 'menu'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
if (Test-Path (Join-Path $PSScriptRoot 'compose.deploy.yml')) {
    $Root = $PSScriptRoot
}
$ManifestFile = Join-Path $Root 'release-manifest.json'
$StateDir = if (Test-Path $ManifestFile) {
    Join-Path $env:ProgramData 'RobotsSystem'
} else {
    Join-Path $Root 'deploy'
}
$activeReleaseFile = Join-Path $StateDir 'active-release-path'
if ((Test-Path $ManifestFile) -and (Test-Path $activeReleaseFile)) {
    $activeRoot = (Get-Content -Raw $activeReleaseFile).Trim()
    $activeManager = Join-Path $activeRoot 'manage.ps1'
    if (
        $activeRoot -and
        -not [IO.Path]::GetFullPath($activeRoot).Equals([IO.Path]::GetFullPath($Root), [StringComparison]::OrdinalIgnoreCase) -and
        (Test-Path $activeManager)
    ) {
        & $activeManager -Action $Action
        exit $LASTEXITCODE
    }
}
$EnvFile = Join-Path $StateDir 'deploy.env'
$ReleaseEnvFile = Join-Path $StateDir 'release.env'
$ComposeFile = Join-Path $Root 'compose.deploy.yml'
if (-not (Test-Path $EnvFile)) {
    throw 'Deployment is not initialized. Run install.cmd first.'
}
$ComposeArgs = @(
    'compose',
    '--project-name', 'robots-system-deploy',
    '--file', $ComposeFile,
    '--env-file', $EnvFile
)
if (Test-Path $ReleaseEnvFile) {
    $ComposeArgs += @('--env-file', $ReleaseEnvFile)
}

function Invoke-Action {
    param([string]$Selected)
    switch ($Selected) {
        'status' {
            & docker @ComposeArgs ps --all
        }
        'start' {
            & (Join-Path $Root 'install.ps1') -SkipFirewall
        }
        'stop' {
            & docker @ComposeArgs down --timeout 60 --remove-orphans
            Write-Host 'Services stopped. Docker volumes were preserved.'
        }
        'restart' {
            & docker @ComposeArgs restart
        }
        'logs' {
            & docker @ComposeArgs logs --tail 200 --follow
        }
    }
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "Operation failed with exit code $LASTEXITCODE."
    }
}

if ($Action -ne 'menu') {
    Invoke-Action $Action
    exit
}

while ($true) {
    Write-Host ''
    Write-Host 'RobotsSystem deployment manager'
    Write-Host '1. Status'
    Write-Host '2. Start or repair'
    Write-Host '3. Restart'
    Write-Host '4. Stop (preserve data)'
    Write-Host '5. Follow logs'
    Write-Host '0. Exit'
    $choice = Read-Host 'Select'
    $selected = switch ($choice) {
        '1' { 'status' }
        '2' { 'start' }
        '3' { 'restart' }
        '4' { 'stop' }
        '5' { 'logs' }
        '0' { return }
        default { $null }
    }
    if ($selected) {
        try {
            Invoke-Action $selected
        } catch {
            Write-Error $_
        }
    }
}
