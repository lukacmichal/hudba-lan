# Publishes the signed release APK to the NAS share and rewrites latest.json.
#
# Usage:
#   .\publish-apk.ps1 -Notes "co je nove"
#
# Build the APK first:
#   .\gradlew.bat -p . assembleRelease
param(
    [string]$Notes = "",
    # Must match the Share + Priečinok fields in the app's update settings.
    [string]$ShareRoot = "\\nas.local\Android\Player"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

# --- read the version straight from gradle so it can never drift from the APK ---
$gradle = Get-Content "$root\app\build.gradle.kts" -Raw
if ($gradle -notmatch 'versionCode\s*=\s*(\d+)') {
    throw "versionCode not found in build.gradle.kts"
}
$versionCode = [int]$Matches[1]
if ($gradle -notmatch 'versionName\s*=\s*"([^"]+)"') {
    throw "versionName not found in build.gradle.kts"
}
$versionName = $Matches[1]

$apkName = "metalmusic-$versionName.apk"
$apkSource = "$root\app\build\outputs\apk\release\$apkName"
if (-not (Test-Path $apkSource)) {
    throw "Release APK not found at $apkSource`nRun: .\gradlew.bat -p . assembleRelease"
}

if (-not (Test-Path $ShareRoot)) {
    throw "NAS folder not reachable: $ShareRoot`nTry: net use \\nas.local\Android /user:nasuser"
}

# --- refuse to publish a build the phone would silently ignore ---
$manifestPath = Join-Path $ShareRoot "latest.json"
if (Test-Path $manifestPath) {
    $existing = Get-Content $manifestPath -Raw | ConvertFrom-Json
    if ($versionCode -le $existing.versionCode) {
        throw ("versionCode $versionCode is not greater than the published " +
               "$($existing.versionCode). Bump versionCode in build.gradle.kts, " +
               "otherwise phones will never see this build.")
    }
}

$apkTarget = Join-Path $ShareRoot $apkName

Write-Host "Copying $apkName -> $ShareRoot ..."
Copy-Item $apkSource $apkTarget -Force

$sha = (Get-FileHash $apkTarget -Algorithm SHA256).Hash.ToLower()

# Write the manifest LAST: until it points at the new APK, phones keep using
# the old one. The reverse order would expose a window where latest.json
# references a file that is missing or still copying.
$json = [ordered]@{
    versionCode = $versionCode
    versionName = $versionName
    apk         = $apkName
    sha256      = $sha
    notes       = $Notes
} | ConvertTo-Json

# UTF-8 without BOM — a BOM would break the app's JSON parser.
[System.IO.File]::WriteAllText($manifestPath, $json, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "Published $versionName (versionCode $versionCode)" -ForegroundColor Green
Write-Host "  sha256 $sha"
Write-Host "  size   $('{0:N1} MB' -f ((Get-Item $apkTarget).Length / 1MB))"
