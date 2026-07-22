[CmdletBinding()]
param(
    [string]$Repository = "eWOOD29/embodied-alife",
    [string]$InstallPath = "$env:USERPROFILE\workspace\local-apps\embodied-alife",
    [string]$GitHubToken = "",
    [switch]$SkipLaunch
)

$ErrorActionPreference = "Stop"
$AssetName = "embodied-alife-update.zip"
$ApiVersion = "2026-03-10"

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Get-Headers([string]$Accept) {
    $headers = @{
        "Accept" = $Accept
        "X-GitHub-Api-Version" = $ApiVersion
        "User-Agent" = "embodied-alife-installer"
    }
    if ($GitHubToken) {
        $headers["Authorization"] = "Bearer $GitHubToken"
    }
    return $headers
}

function Get-ExpectedHash($Release, $PackageAsset, [string]$TempDirectory) {
    if ($PackageAsset.digest -and $PackageAsset.digest.StartsWith("sha256:")) {
        $digestValue = $PackageAsset.digest.Substring(7).ToLowerInvariant()
        if ($digestValue -notmatch '^[0-9a-f]{64}$') {
            throw "GitHub returned a malformed SHA-256 asset digest."
        }
        return $digestValue
    }
    $checksumAsset = $Release.assets | Where-Object {
        $_.name -eq "$AssetName.sha256" -or $_.name -eq "$AssetName.sha256.txt"
    } | Select-Object -First 1
    if (-not $checksumAsset) {
        throw "The release has neither a GitHub SHA-256 digest nor a checksum asset."
    }
    $checksumPath = Join-Path $TempDirectory $checksumAsset.name
    Invoke-WebRequest -UseBasicParsing -Uri $checksumAsset.url -Headers (Get-Headers "application/octet-stream") -OutFile $checksumPath
    $line = (Get-Content -LiteralPath $checksumPath -TotalCount 1).Trim()
    if ($line -notmatch '^([0-9a-fA-F]{64})\s+\*?(.+)$') {
        throw "The release checksum file is malformed."
    }
    if ([IO.Path]::GetFileName($Matches[2]) -ne $AssetName) {
        throw "The release checksum refers to a different filename."
    }
    return $Matches[1].ToLowerInvariant()
}

if ($Repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') {
    throw "Repository must use owner/repository format."
}

$tempDirectory = Join-Path ([IO.Path]::GetTempPath()) ("embodied-alife-install-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempDirectory | Out-Null

try {
    Write-Step "Reading the latest published GitHub release"
    $releaseUri = "https://api.github.com/repos/$Repository/releases/latest"
    $release = Invoke-RestMethod -Uri $releaseUri -Headers (Get-Headers "application/vnd.github+json")
    $packageAsset = $release.assets | Where-Object { $_.name -eq $AssetName } | Select-Object -First 1
    if (-not $packageAsset) {
        throw "Release $($release.tag_name) does not contain $AssetName."
    }
    if ([Int64]$packageAsset.size -gt 104857600) {
        throw "The release package exceeds the 100 MiB download limit."
    }

    Write-Step "Downloading and verifying $($release.tag_name)"
    $archivePath = Join-Path $tempDirectory $AssetName
    Invoke-WebRequest -UseBasicParsing -Uri $packageAsset.url -Headers (Get-Headers "application/octet-stream") -OutFile $archivePath
    $expectedHash = Get-ExpectedHash $release $packageAsset $tempDirectory
    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedHash) {
        throw "SHA-256 verification failed. Expected $expectedHash but downloaded $actualHash."
    }

    Write-Step "Validating archive paths and size"
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($archivePath)
    try {
        if ($archive.Entries.Count -lt 1 -or $archive.Entries.Count -gt 5000) {
            throw "The release archive has an invalid file count."
        }
        [Int64]$expandedBytes = 0
        $archiveNames = @{}
        foreach ($entry in $archive.Entries) {
            $name = $entry.FullName.Replace('\', '/')
            $parts = $name.Split('/', [System.StringSplitOptions]::RemoveEmptyEntries)
            if ([string]::IsNullOrWhiteSpace($name) -or $name.StartsWith('/') -or $name -match '^[A-Za-z]:' -or $parts -contains '..') {
                throw "The release archive contains an unsafe path: $name"
            }
            $nameKey = $name.TrimEnd('/')
            if ($nameKey -and $archiveNames.ContainsKey($nameKey)) {
                throw "The release archive contains a duplicate path: $nameKey"
            }
            if ($nameKey) { $archiveNames[$nameKey] = $true }
            $expandedBytes += $entry.Length
            if ($expandedBytes -gt 262144000) {
                throw "The release archive exceeds the 250 MiB extraction limit."
            }
            $unixType = (($entry.ExternalAttributes -shr 16) -band 0xF000)
            if ($unixType -eq 0xA000) {
                throw "The release archive contains a symbolic link: $name"
            }
        }
    }
    finally {
        $archive.Dispose()
    }

    $stagedPath = Join-Path $tempDirectory "staged"
    Expand-Archive -LiteralPath $archivePath -DestinationPath $stagedPath -Force
    $manifestPath = Join-Path $stagedPath "update-manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath)) {
        throw "The release package has no update-manifest.json."
    }
    $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
    if ($manifest.app_id -ne "embodied-alife" -or $manifest.schema_version -ne 1) {
        throw "The release package manifest is not valid for Embodied Artificial Life."
    }
    $releaseVersion = [string]$release.tag_name
    if ($releaseVersion.StartsWith('v')) { $releaseVersion = $releaseVersion.Substring(1) }
    if ([string]$manifest.version -ne $releaseVersion) {
        throw "The release tag and package manifest versions do not match."
    }

    Write-Step "Installing files into $InstallPath"
    New-Item -ItemType Directory -Force -Path $InstallPath | Out-Null
    $installRoot = [IO.Path]::GetFullPath($InstallPath).TrimEnd('\') + '\'
    $managedNames = @{}
    foreach ($relative in $manifest.managed_paths) {
        if (-not ($relative -is [string]) -or [string]::IsNullOrWhiteSpace($relative)) {
            throw "The package contains an invalid managed path."
        }
        $normalized = $relative.Replace('\', '/')
        $parts = $normalized.Split('/', [System.StringSplitOptions]::RemoveEmptyEntries)
        if ($normalized.StartsWith('/') -or $normalized -match '^[A-Za-z]:' -or $parts -contains '..') {
            throw "The package contains an unsafe managed path: $relative"
        }
        if ($managedNames.ContainsKey($normalized)) {
            throw "The package contains a duplicate managed path: $relative"
        }
        $managedNames[$normalized] = $true
        if ($normalized -eq ".env" -or $normalized.StartsWith(".venv/") -or $normalized.StartsWith("data/") -or $normalized.StartsWith(".git/")) {
            throw "The package attempted to manage a protected path: $relative"
        }
        $nativeRelative = $normalized.Replace('/', [IO.Path]::DirectorySeparatorChar)
        $source = Join-Path $stagedPath $nativeRelative
        $destination = Join-Path $InstallPath $nativeRelative
        $destinationFull = [IO.Path]::GetFullPath($destination)
        if (-not $destinationFull.StartsWith($installRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "The package path escapes the installation directory: $relative"
        }
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "The package is missing a managed file: $relative"
        }
        $destinationDirectory = Split-Path -Parent $destination
        New-Item -ItemType Directory -Force -Path $destinationDirectory | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }

    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv was not found on PATH. Install uv, reopen PowerShell, and run this installer again."
    }

    Write-Step "Creating the project-local virtual environment"
    $pythonPath = Join-Path $InstallPath ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        & uv venv --python 3.11 (Join-Path $InstallPath ".venv")
        if ($LASTEXITCODE -ne 0) { throw "uv venv failed with exit code $LASTEXITCODE." }
    }

    Write-Step "Installing project dependencies"
    & uv pip install --python $pythonPath -e $InstallPath
    if ($LASTEXITCODE -ne 0) { throw "uv pip install failed with exit code $LASTEXITCODE." }

    $envPath = Join-Path $InstallPath ".env"
    if (-not (Test-Path -LiteralPath $envPath)) {
        Copy-Item -LiteralPath (Join-Path $InstallPath ".env.example") -Destination $envPath
    }

    Write-Step "Running the package validator"
    & $pythonPath (Join-Path $InstallPath "scripts\validate_package.py")
    if ($LASTEXITCODE -ne 0) { throw "Package validation failed with exit code $LASTEXITCODE." }

    Write-Host "`nInstalled Embodied Artificial Life $($manifest.version) successfully." -ForegroundColor Green
    Write-Host "Location: $InstallPath"
    Write-Host "Local URL: http://127.0.0.1:8797/"
    Write-Host "Tailscale: run scripts\enable-tailscale-access.ps1 once from an Administrator PowerShell window."

    if (-not $SkipLaunch) {
        Write-Step "Launching Embodied Artificial Life"
        Start-Process -FilePath (Join-Path $InstallPath "start-embodied-alife.bat") -WorkingDirectory $InstallPath
    }
}
finally {
    Remove-Item -LiteralPath $tempDirectory -Recurse -Force -ErrorAction SilentlyContinue
}
