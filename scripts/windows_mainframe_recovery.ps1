param(
    [Parameter(Mandatory = $true)]
    [string]$PlanPath,

    [string]$MainframeRoot = "\\MainFrame",

    [string]$GuassianAbsolutelyRoot = "F:\Guassian Dropbox\Steven Guas\Absolutely",

    [string]$StagingRoot = "C:\Users\Public\Documents\Paracosm_Mainframe_Recovery_20260729",

    [switch]$ProbeOnly,

    [switch]$FullPackages,

    [int]$MaximumPhase = 5
)

$ErrorActionPreference = "Stop"

function Convert-ToWindowsPath {
    param([string]$Value)
    return ($Value -replace "/", "\")
}

function Resolve-PackageSource {
    param(
        [object]$Package,
        [string]$Mainframe,
        [string]$Guassian
    )

    $relative = Convert-ToWindowsPath $Package.packageRoot
    switch ($Package.source) {
        "mainframe" {
            return Join-Path $Mainframe $relative
        }
        "guassian_dropbox" {
            return Join-Path $Guassian $relative
        }
        "windows_absolute" {
            return $relative
        }
        default {
            return $null
        }
    }
}

function Copy-Package {
    param(
        [string]$Source,
        [string]$Destination
    )

    if (Test-Path -LiteralPath $Source -PathType Leaf) {
        New-Item -ItemType Directory -Force -Path (Split-Path $Destination) |
            Out-Null
        Copy-Item -LiteralPath $Source -Destination $Destination -Force
        return
    }

    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    & robocopy $Source $Destination /E /COPY:DAT /DCOPY:DAT /R:2 /W:2 /XJ /NFL /NDL /NJH /NJS
    if ($LASTEXITCODE -gt 7) {
        throw "robocopy failed with exit code $LASTEXITCODE for $Source"
    }
}

function Resolve-RequiredSource {
    param(
        [object]$Package,
        [string]$RequiredPath,
        [string]$Mainframe,
        [string]$Guassian
    )

    $relative = Convert-ToWindowsPath $RequiredPath
    switch ($Package.source) {
        "mainframe" {
            return Join-Path $Mainframe $relative
        }
        "guassian_dropbox" {
            return Join-Path $Guassian $relative
        }
        "windows_absolute" {
            return $relative
        }
        default {
            return $null
        }
    }
}

$resolvedPlan = (Resolve-Path -LiteralPath $PlanPath).Path
$plan = Get-Content -LiteralPath $resolvedPlan -Raw | ConvertFrom-Json
$selected = @(
    $plan.packages |
        Where-Object {
            [int]$_.phase -le $MaximumPhase -and
            $_.source -in @("mainframe", "guassian_dropbox", "windows_absolute")
        }
)

$results = @()
foreach ($package in $selected) {
    $source = Resolve-PackageSource `
        -Package $package `
        -Mainframe $MainframeRoot `
        -Guassian $GuassianAbsolutelyRoot
    $exists = $false
    if ($null -ne $source) {
        $exists = Test-Path -LiteralPath $source
    }
    $result = [ordered]@{
        phase = [int]$package.phase
        sourceType = [string]$package.source
        packageRoot = [string]$package.packageRoot
        sourcePath = $source
        exists = $exists
        cutIds = @($package.cutIds)
        requiredPathCount = [int]$package.requiredPathCount
        requiredFilesOnly = -not [bool]$FullPackages
        copied = $false
        destinationPath = $null
        fileCount = 0
        byteCount = 0
        sha256Manifest = @()
        error = $null
    }

    if (-not $exists -or $ProbeOnly) {
        $results += [pscustomobject]$result
        continue
    }

    try {
        $sourceFolder = $package.source -replace "_", "-"
        $destinationRoot = Join-Path $StagingRoot $sourceFolder
        $destination = $null
        $copiedDestinations = @()
        if ($FullPackages) {
            $destination = Join-Path `
                $destinationRoot `
                (Convert-ToWindowsPath $package.packageRoot)
            Copy-Package -Source $source -Destination $destination
        }
        else {
            foreach ($requiredPath in @($package.requiredPaths)) {
                $requiredSource = Resolve-RequiredSource `
                    -Package $package `
                    -RequiredPath $requiredPath `
                    -Mainframe $MainframeRoot `
                    -Guassian $GuassianAbsolutelyRoot
                if (-not (Test-Path -LiteralPath $requiredSource -PathType Leaf)) {
                    throw "required file is absent: $requiredSource"
                }
                $requiredDestination = Join-Path `
                    $destinationRoot `
                    (Convert-ToWindowsPath $requiredPath)
                New-Item `
                    -ItemType Directory `
                    -Force `
                    -Path (Split-Path $requiredDestination) |
                    Out-Null
                Copy-Item `
                    -LiteralPath $requiredSource `
                    -Destination $requiredDestination `
                    -Force
                $copiedDestinations += Get-Item -LiteralPath $requiredDestination
            }
            $destination = $destinationRoot
        }
        $files = @(
            if (-not $FullPackages) {
                $copiedDestinations
            }
            elseif (Test-Path -LiteralPath $destination -PathType Leaf) {
                Get-Item -LiteralPath $destination
            }
            else {
                Get-ChildItem -LiteralPath $destination -File -Recurse
            }
        )
        $hashes = foreach ($file in $files) {
            $hash = Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256
            [ordered]@{
                relativePath = $file.FullName.Substring($StagingRoot.Length).TrimStart("\")
                bytes = [int64]$file.Length
                sha256 = $hash.Hash.ToLowerInvariant()
            }
        }
        $result.copied = $true
        $result.destinationPath = $destination
        $result.fileCount = $files.Count
        $result.byteCount = [int64](($files | Measure-Object Length -Sum).Sum)
        $result.sha256Manifest = @($hashes)
    }
    catch {
        $result.error = $_.Exception.Message
    }
    $results += [pscustomobject]$result
}

New-Item -ItemType Directory -Force -Path $StagingRoot | Out-Null
$output = [ordered]@{
    schemaVersion = 1
    generatedAt = (Get-Date).ToUniversalTime().ToString("o")
    planPath = $resolvedPlan
    mainframeRoot = $MainframeRoot
    guassianAbsolutelyRoot = $GuassianAbsolutelyRoot
    stagingRoot = $StagingRoot
    probeOnly = [bool]$ProbeOnly
    fullPackages = [bool]$FullPackages
    maximumPhase = $MaximumPhase
    summary = [ordered]@{
        packageCount = $results.Count
        existingPackageCount = @($results | Where-Object exists).Count
        copiedPackageCount = @($results | Where-Object copied).Count
        failedPackageCount = @($results | Where-Object { $_.error }).Count
        totalCopiedFiles = [int](($results | Measure-Object fileCount -Sum).Sum)
        totalCopiedBytes = [int64](($results | Measure-Object byteCount -Sum).Sum)
    }
    packages = $results
}
$resultPath = Join-Path $StagingRoot "mainframe-recovery-results.json"
$output | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $resultPath -Encoding UTF8
Write-Host "Wrote recovery results to $resultPath"
$output.summary | Format-List
