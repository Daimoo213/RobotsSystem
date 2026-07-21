[CmdletBinding()]
param(
    [switch]$SkipFirewall,
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
if (Test-Path (Join-Path $PSScriptRoot 'compose.deploy.yml')) {
    $Root = $PSScriptRoot
}
$ComposeFile = Join-Path $Root 'compose.deploy.yml'
$ManifestFile = Join-Path $Root 'release-manifest.json'
$PackageDeployDir = Join-Path $Root 'deploy'
$IsPackagedRelease = Test-Path $ManifestFile
$StateDir = if ($IsPackagedRelease) {
    Join-Path $env:ProgramData 'RobotsSystem'
} else {
    $PackageDeployDir
}
$EnvFile = Join-Path $StateDir 'deploy.env'
$ReleaseEnvFile = Join-Path $StateDir 'release.env'
$PreviousReleaseEnvFile = Join-Path $StateDir 'previous-release.env'
$InstalledVersionFile = Join-Path $StateDir 'installed-version'
$ImageArchive = Join-Path $PackageDeployDir 'images.tar'
$ProjectName = 'robots-system-deploy'
$script:ReleaseMode = 'source'
$script:ReleaseVersion = 'dev'
$script:ReleaseImages = @{}
$script:PreviousReleaseConfigSaved = $false
$script:RollbackTags = @{}
$script:DeploymentAttempted = $false

function Get-ComposeArguments {
    $arguments = @(
        'compose',
        '--project-name', $ProjectName,
        '--file', $ComposeFile,
        '--env-file', $EnvFile
    )
    if (Test-Path $ReleaseEnvFile) {
        $arguments += @('--env-file', $ReleaseEnvFile)
    }
    return $arguments
}

function Invoke-Docker {
    param([string[]]$Arguments)
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker command failed with exit code $LASTEXITCODE."
    }
}

function New-RandomSecret {
    param([int]$Bytes)
    $buffer = New-Object byte[] $Bytes
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($buffer)
    } finally {
        $generator.Dispose()
    }
    return [Convert]::ToBase64String($buffer).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Initialize-Environment {
    if (Test-Path $EnvFile) {
        Write-Host "Keeping existing deployment configuration: $EnvFile"
        return
    }
    $content = @(
        'APP_NAME=RobotsClusterScheduler',
        'BIND_HOST=0.0.0.0',
        'BACKEND_PORT=8000',
        'PM_PORT=8080',
        'OM_PORT=8081',
        '',
        'PG_USER=scheduler',
        "PG_PASSWORD=$(New-RandomSecret 32)",
        'PG_DB=scheduler',
        "REDIS_PASSWORD=$(New-RandomSecret 32)",
        '',
        "JWT_SECRET=$(New-RandomSecret 48)",
        "DEVICE_GATEWAY_API_KEY=$(New-RandomSecret 48)",
        "INITIAL_SETUP_TOKEN=$(New-RandomSecret 32)"
    ) -join [Environment]::NewLine
    $encoding = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($EnvFile, $content + [Environment]::NewLine, $encoding)
    Write-Host 'Created deployment configuration with unique local secrets.'
}

function Test-Environment {
    $values = @{}
    foreach ($line in Get-Content $EnvFile) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#') -or -not $trimmed.Contains('=')) {
            continue
        }
        $name, $value = $trimmed -split '=', 2
        $values[$name.Trim()] = $value.Trim().Trim('"').Trim("'")
    }
    $required = @(
        'APP_NAME', 'BIND_HOST', 'BACKEND_PORT', 'PM_PORT', 'OM_PORT',
        'PG_USER', 'PG_PASSWORD', 'PG_DB', 'REDIS_PASSWORD',
        'JWT_SECRET', 'DEVICE_GATEWAY_API_KEY', 'INITIAL_SETUP_TOKEN'
    )
    foreach ($name in $required) {
        if (-not $values.ContainsKey($name) -or -not $values[$name]) {
            throw "Deployment setting is missing: $name"
        }
    }
    $secretNames = @(
        'PG_PASSWORD', 'REDIS_PASSWORD', 'JWT_SECRET',
        'DEVICE_GATEWAY_API_KEY', 'INITIAL_SETUP_TOKEN'
    )
    foreach ($name in $secretNames) {
        $normalized = $values[$name].ToLowerInvariant()
        if ($values[$name].Length -lt 24 -or $normalized.StartsWith('replace-with-') -or $normalized -eq 'changeme') {
            throw "Deployment secret is a placeholder or too short: $name"
        }
    }
    $uniqueSecrets = @($secretNames | ForEach-Object { $values[$_] } | Select-Object -Unique)
    if ($uniqueSecrets.Count -ne $secretNames.Count) {
        throw 'Deployment secrets must all be different.'
    }
    foreach ($name in @('BACKEND_PORT', 'PM_PORT', 'OM_PORT')) {
        $port = 0
        if (-not [int]::TryParse($values[$name], [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
            throw "Deployment port is invalid: $name"
        }
    }
    Write-Host 'Deployment configuration is valid.'
}

function Test-ReleaseManifest {
    if (-not (Test-Path $ManifestFile)) {
        return
    }
    Write-Host 'Verifying release package integrity...'
    $manifest = Get-Content -Raw -Encoding UTF8 $ManifestFile | ConvertFrom-Json
    foreach ($entry in $manifest.files.PSObject.Properties) {
        $relative = $entry.Name.Replace('/', [IO.Path]::DirectorySeparatorChar)
        $path = Join-Path $Root $relative
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Release file is missing: $relative"
        }
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
        if ($actual -ne [string]$entry.Value) {
            throw "Release file checksum failed: $relative"
        }
    }
    Write-Host 'Release package integrity is valid.'
}

function Set-ReleaseConfiguration {
    $images = @{
        BACKEND_IMAGE = 'robots-system-deploy-backend:latest'
        PM_IMAGE = 'robots-system-deploy-pm:latest'
        OM_IMAGE = 'robots-system-deploy-om:latest'
        POSTGRES_IMAGE = 'postgres:16-alpine'
        REDIS_IMAGE = 'redis:7.2-alpine'
    }
    $version = 'dev'
    $mode = 'source'
    if (Test-Path $ManifestFile) {
        $manifest = Get-Content -Raw -Encoding UTF8 $ManifestFile | ConvertFrom-Json
        if ($manifest.version) {
            $version = [string]$manifest.version
        }
        if ($manifest.mode) {
            $mode = [string]$manifest.mode
        }
        $manifestImages = $manifest.images
        if ($manifestImages) {
            $images.BACKEND_IMAGE = [string]$manifestImages.backend
            $images.PM_IMAGE = [string]$manifestImages.pm
            $images.OM_IMAGE = [string]$manifestImages.om
            $images.POSTGRES_IMAGE = [string]$manifestImages.postgres
            $images.REDIS_IMAGE = [string]$manifestImages.redis
        }
    } else {
        $versionFile = Join-Path $Root 'VERSION'
        if (Test-Path $versionFile) {
            $version = (Get-Content -Raw $versionFile).Trim()
        }
    }
    foreach ($name in $images.Keys) {
        if (-not $images[$name] -or $images[$name] -match '\s') {
            throw "Invalid release image reference: $name"
        }
    }
    if ($mode -notin @('source', 'offline', 'registry')) {
        throw "Unsupported release delivery mode: $mode"
    }
    $content = @(
        "RELEASE_VERSION=$version",
        "BACKEND_IMAGE=$($images.BACKEND_IMAGE)",
        "PM_IMAGE=$($images.PM_IMAGE)",
        "OM_IMAGE=$($images.OM_IMAGE)",
        "POSTGRES_IMAGE=$($images.POSTGRES_IMAGE)",
        "REDIS_IMAGE=$($images.REDIS_IMAGE)"
    ) -join [Environment]::NewLine
    $content += [Environment]::NewLine
    if (Test-Path $ReleaseEnvFile) {
        $existing = Get-Content -Raw $ReleaseEnvFile
        if ($existing -ne $content) {
            Copy-Item -LiteralPath $ReleaseEnvFile -Destination $PreviousReleaseEnvFile -Force
            $script:PreviousReleaseConfigSaved = $true
        }
    }
    $encoding = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($ReleaseEnvFile, $content, $encoding)
    $script:ReleaseMode = $mode
    $script:ReleaseVersion = $version
    $script:ReleaseImages = $images
    Write-Host "Selected release v$version ($mode)."
}

function Import-OfflineImages {
    if (-not (Test-Path $ImageArchive)) {
        return $false
    }
    $required = @($script:ReleaseImages.Values)
    $archiveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ImageArchive).Hash.ToLowerInvariant()
    $marker = Join-Path $StateDir 'images-loaded.sha256'
    $needsImport = -not (Test-Path $marker) -or ((Get-Content -Raw $marker).Trim() -ne $archiveHash)
    foreach ($image in $required) {
        & docker image inspect $image *> $null
        if ($LASTEXITCODE -ne 0) {
            $needsImport = $true
        }
    }
    if ($needsImport) {
        Write-Host 'Loading bundled Docker images. This can take several minutes...'
        Invoke-Docker @('load', '--input', $ImageArchive)
        [IO.File]::WriteAllText($marker, $archiveHash + [Environment]::NewLine)
    } else {
        Write-Host 'Bundled Docker images are already loaded.'
    }
    return $true
}

function Import-RegistryImages {
    if ($script:ReleaseMode -ne 'registry') {
        return
    }
    Write-Host "Pulling immutable images for v$($script:ReleaseVersion)..."
    Invoke-Docker ($script:ComposeArgs + @('pull', 'postgres', 'redis', 'backend', 'pm', 'om'))
}

function Get-EnvValue {
    param([string]$Name)
    $line = Get-Content $EnvFile | Where-Object { $_ -match "^$([Regex]::Escape($Name))=" } | Select-Object -First 1
    if (-not $line) {
        throw "Missing deployment setting: $Name"
    }
    return ($line -split '=', 2)[1].Trim()
}

function Backup-DatabaseIfNeeded {
    $installedVersion = if (Test-Path $InstalledVersionFile) {
        (Get-Content -Raw $InstalledVersionFile).Trim()
    } else {
        ''
    }
    if ($installedVersion -eq $script:ReleaseVersion) {
        Write-Host "Release v$installedVersion is already installed; upgrade backup is not required."
        return
    }
    $composeArguments = $script:ComposeArgs
    $container = (& docker @composeArguments ps --status running --quiet postgres | Select-Object -First 1)
    if ($LASTEXITCODE -ne 0) {
        throw 'Unable to inspect the running PostgreSQL container.'
    }
    if (-not $container) {
        return
    }
    $container = $container.Trim()
    $backupDir = Join-Path $StateDir 'backups'
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
    $name = "robots_system_before_v$($script:ReleaseVersion)_$stamp.dump"
    $remotePath = "/tmp/$name"
    $backupCommand = 'PGPASSWORD="$POSTGRES_PASSWORD" exec pg_dump --format=custom --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --file "{0}"' -f $remotePath
    try {
        Invoke-Docker @('exec', $container, 'sh', '-c', $backupCommand)
        Invoke-Docker @('cp', ('{0}:{1}' -f $container, $remotePath), (Join-Path $backupDir $name))
    } finally {
        & docker exec $container rm -f $remotePath *> $null
    }
    $backupPath = Join-Path $backupDir $name
    if (-not (Test-Path $backupPath) -or (Get-Item $backupPath).Length -eq 0) {
        throw 'Database backup is empty; update was cancelled.'
    }
    Write-Host "Pre-upgrade database backup created: $backupPath"
}

function Save-ApplicationRollbackImages {
    foreach ($service in @('backend', 'pm', 'om')) {
        $composeArguments = $script:ComposeArgs
        $container = (& docker @composeArguments ps --status running --quiet $service | Select-Object -First 1)
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to inspect running service: $service"
        }
        if (-not $container) {
            continue
        }
        $imageId = (& docker inspect $container.Trim() --format '{{.Image}}').Trim()
        if ($LASTEXITCODE -ne 0 -or -not $imageId) {
            throw "Unable to inspect the current image for service: $service"
        }
        $rollbackTag = "robots-system-rollback-$service`:previous"
        Invoke-Docker @('image', 'tag', $imageId, $rollbackTag)
        $script:RollbackTags[$service] = $rollbackTag
    }
}

function Restore-PreviousRelease {
    if ($script:PreviousReleaseConfigSaved -and (Test-Path $PreviousReleaseEnvFile)) {
        Copy-Item -LiteralPath $PreviousReleaseEnvFile -Destination $ReleaseEnvFile -Force
        Write-Warning 'Restored the previous release image configuration.'
    }
    if (-not $script:DeploymentAttempted -or $script:RollbackTags.Count -eq 0) {
        return
    }
    $localTargets = @{
        backend = 'robots-system-deploy-backend:latest'
        pm = 'robots-system-deploy-pm:latest'
        om = 'robots-system-deploy-om:latest'
    }
    foreach ($service in $script:RollbackTags.Keys) {
        Invoke-Docker @('image', 'tag', $script:RollbackTags[$service], $localTargets[$service])
    }
    $script:ComposeArgs = Get-ComposeArguments
    Write-Warning 'Attempting application rollback with the previous images...'
    Invoke-Docker ($script:ComposeArgs + @(
        'up', '--detach', '--no-build', '--remove-orphans',
        '--wait', '--wait-timeout', '180'
    ))
    Write-Warning 'Previous application images are running. The database backup was preserved.'
}

function Enable-PrivateFirewall {
    if ($SkipFirewall) {
        return
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    $isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Write-Warning 'Run install.cmd as administrator to open LAN firewall ports automatically.'
        return
    }
    if (-not (Get-Command New-NetFirewallRule -ErrorAction SilentlyContinue)) {
        Write-Warning 'Windows Firewall cmdlets are unavailable; firewall rules were not changed.'
        return
    }
    $ports = @(
        (Get-EnvValue 'BACKEND_PORT'),
        (Get-EnvValue 'PM_PORT'),
        (Get-EnvValue 'OM_PORT')
    )
    $ruleName = 'RobotsSystem private LAN services'
    Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $ports -Profile Private | Out-Null
    Write-Host "Opened private-network TCP ports: $($ports -join ', ')"
}

function Get-LanAddress {
    try {
        $configuration = Get-NetIPConfiguration |
            Where-Object { $_.IPv4DefaultGateway -and $_.IPv4Address } |
            Select-Object -First 1
        if ($configuration) {
            return $configuration.IPv4Address.IPAddress
        }
    } catch {
        return '127.0.0.1'
    }
    return '127.0.0.1'
}

function Test-HttpEndpoint {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 5
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
    } catch {
        return $false
    }
}

New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
$logPath = Join-Path $StateDir 'install.log'
Start-Transcript -Path $logPath -Append | Out-Null
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Docker Desktop is not installed or docker.exe is not in PATH.'
    }
    & docker info --format '{{.ServerVersion}}' *> $null
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker Engine is not running. Start Docker Desktop and run install.cmd again.'
    }
    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker Compose v2 is unavailable.'
    }
    if (-not (Test-Path $ComposeFile)) {
        throw "Missing Compose file: $ComposeFile"
    }

    Test-ReleaseManifest
    Initialize-Environment
    Test-Environment
    Set-ReleaseConfiguration
    $script:ComposeArgs = Get-ComposeArguments
    Invoke-Docker ($script:ComposeArgs + @('config', '--quiet'))
    if ($ValidateOnly) {
        Write-Host 'Release validation completed without changing containers.'
        return
    }
    Backup-DatabaseIfNeeded
    Save-ApplicationRollbackImages
    $offline = Import-OfflineImages
    Import-RegistryImages

    $modeArgument = if ($script:ReleaseMode -eq 'source') { '--build' } else { '--no-build' }
    Write-Host "Starting RobotsSystem deployment ($modeArgument)..."
    $script:DeploymentAttempted = $true
    try {
        Invoke-Docker ($script:ComposeArgs + @(
            'up', '--detach', $modeArgument, '--remove-orphans',
            '--wait', '--wait-timeout', '240'
        ))
    } catch {
        $composeArguments = $script:ComposeArgs
        & docker @composeArguments ps --all
        & docker @composeArguments logs --tail 120
        throw
    }

    $backendPort = Get-EnvValue 'BACKEND_PORT'
    $pmPort = Get-EnvValue 'PM_PORT'
    $omPort = Get-EnvValue 'OM_PORT'
    $probes = @(
        "http://127.0.0.1:$backendPort/ready",
        "http://127.0.0.1:$pmPort/api/auth/setup-status",
        "http://127.0.0.1:$omPort/api/auth/setup-status"
    )
    foreach ($probe in $probes) {
        if (-not (Test-HttpEndpoint $probe)) {
            throw "Deployment started, but the endpoint is unavailable: $probe"
        }
    }

    [IO.File]::WriteAllText($InstalledVersionFile, $script:ReleaseVersion + [Environment]::NewLine)
    [IO.File]::WriteAllText((Join-Path $StateDir 'active-release-path'), $Root + [Environment]::NewLine)

    Enable-PrivateFirewall
    $address = Get-LanAddress
    Write-Host ''
    Write-Host 'RobotsSystem deployment is healthy.' -ForegroundColor Green
    Write-Host ('PM:      http://{0}:{1}' -f $address, $pmPort)
    Write-Host ('O&M:     http://{0}:{1}' -f $address, $omPort)
    Write-Host ('Gateway: http://{0}:{1}' -f $address, $backendPort)
    Write-Host "Initial setup token is stored in $EnvFile and was not printed."
    Write-Host "Installation log: $logPath"
} catch {
    $failure = $_
    Write-Host ''
    try {
        Restore-PreviousRelease
    } catch {
        Write-Warning "Automatic application rollback also failed: $($_.Exception.Message)"
    }
    Write-Error $failure
    exit 1
} finally {
    Stop-Transcript | Out-Null
}
