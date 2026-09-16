<#
.SYNOPSIS
  Vyda novu verziu WINDOWSOVEHO prehravaca na NAS (share Android, priecinok
  PlayerPC), odkial si ju appka na oboch notebookoch vezme sama.

.DESCRIPTION
  Androidovy klient sa nahrava cez ..\nahraj-na-nas.ps1 -Appka player.
  Tento skript je jeho dvojcatom pre windowsovu appku a drzi sa tej istej
  konvencie "manifest":

      \\nas.local\Android\PlayerPC\
          latest.json                   verzia + meno balika + SHA-256
          metalmusic-pc-<verzia>.zip    cela appka
          nainstaluj.cmd                prva instalacia na novom notebooku
          README.txt
          konfiguracia\                 config.txt a spankove zoznamy

  Appka pri starte cita IBA latest.json; balik stiahne az po potvrdeni a pred
  instalaciou overi jeho SHA-256.

  PRED nahratim zvys OBE cisla v music_player\__init__.py (__version__ aj
  __version_code__). Appka porovnava vyhradne __version_code__ — zabudnute
  zvysenie znamena, ze sa nova verzia na druhom notebooku nikdy neponukne.
  Skript to strazi: rovnaka alebo nizsia verzia nez na NAS-e sa odmietne.

  Poverenia berie z ..\nas-credentials.local, rovnako ako nahraj-na-nas.ps1.
  Ten isty subor pouziva aj samotna appka, ked sa na NAS potrebuje prihlasit;
  na druhom notebooku, kde nie je, ma poverenie ulozene Windows (uklada ho
  instalator nas\nainstaluj.ps1). Ziadne heslo teda nie je ani v balicku, ani
  v config.txt.

.PARAMETER Poznamka
  Text "co je nove", ktory appka ukaze v dialogu o novej verzii. Bez neho sa
  poznamka nezobrazi — to je lepsie nez veta z minuleho vydania, ktora uz
  neplati.

.PARAMETER Skus
  Len ukaze, co by sa nahralo. Nic nezapise.

.PARAMETER AjStarsiu
  Povoli nahrat starsiu verziu, nez ktora uz na NAS-e lezi.

.EXAMPLE
  .\nahraj-pc-na-nas.ps1 -Skus
  .\nahraj-pc-na-nas.ps1 -Poznamka "Prehravac sa uz aktualizuje sam z NAS-u."
#>
[CmdletBinding()]
param(
    [string]$Poznamka = '',
    [switch]$Skus,
    [switch]$AjStarsiu
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem

$Projekt  = $PSScriptRoot
$NasHost  = 'nas.local'
$Share    = 'Android'
$CielDirName = 'PlayerPC'
# Jediny zdroj prihlasovacich udajov v celom C:\NAS.
$CredFile = Join-Path (Split-Path $Projekt -Parent) 'nas-credentials.local'

# --- co ide do balika --------------------------------------------------------
# Vypocet zamerne NIE JE "vsetko okrem" — v priecinku lezia aj JVM crash dumpy,
# screenshoty z ladenia a cely androidovy strom. Menny zoznam znamena, ze na
# NAS ide len to, co appka naozaj potrebuje.
$Subory = @(
    'app.pyw'
    'spustit.cmd'
    'vytvor-skratku.cmd'
    'vytvor-skratku.ps1'
    'aktualizuj.ps1'
    'oprava-lan-pristupu.cmd'
    'hudba-po-zobudeni.cmd'
    'hudba-po-zobudeni.ps1'
    'spusti-ak-nebezi.cmd'
    'README.md'
    # Vzory konfiguracie. Aktualizacia ich NEPREPISE — do instalacie sa
    # dostanu len vtedy, ked tam chybaju (cerstvy notebook).
    'config.txt'
    'spanok.m3u'
    'spanok2.m3u'
)
$Priecinky = @(
    @{ cesta = 'music_player'; vzorky = @('*.py', 'icon.ico', 'icon.png') }
    @{ cesta = 'tests';        vzorky = @('*.py') }
)

# --- verzia ------------------------------------------------------------------
$initPy = Join-Path $Projekt 'music_player\__init__.py'
$init = Get-Content $initPy -Raw
$verzia = ([regex]::Match($init, '__version__\s*=\s*"([^"]+)"')).Groups[1].Value
$kod    = ([regex]::Match($init, '__version_code__\s*=\s*(\d+)')).Groups[1].Value
if (-not $verzia -or -not $kod) {
    throw "V $initPy sa nepodarilo najst __version__ a __version_code__."
}
$kod = [int]$kod
$zipMeno = "metalmusic-pc-$verzia.zip"

# --- zabalit -----------------------------------------------------------------
$docasny = Join-Path $env:TEMP ("metalplayer-vydanie-" + [guid]::NewGuid().ToString('N'))
$staging = Join-Path $docasny 'balik'
New-Item -ItemType Directory -Path $staging -Force | Out-Null

$chybaju = @()
foreach ($s in $Subory) {
    $zdroj = Join-Path $Projekt $s
    if (Test-Path $zdroj) { Copy-Item $zdroj -Destination (Join-Path $staging $s) -Force }
    else { $chybaju += $s }
}
foreach ($p in $Priecinky) {
    $zdroj = Join-Path $Projekt $p.cesta
    if (-not (Test-Path $zdroj)) { $chybaju += $p.cesta; continue }
    $ciel = Join-Path $staging $p.cesta
    New-Item -ItemType Directory -Path $ciel -Force | Out-Null
    foreach ($vzorka in $p.vzorky) {
        Get-ChildItem -Path $zdroj -Filter $vzorka -File |
            ForEach-Object { Copy-Item $_.FullName -Destination $ciel -Force }
    }
}
if ($chybaju) {
    # Nie chyba: appka moze mat prazdny spanok2.m3u a testy nemusia byt vsade.
    Write-Host "  [i] v balicku nebudu (neexistuju): $($chybaju -join ', ')" -ForegroundColor DarkGray
}

$zipCesta = Join-Path $docasny $zipMeno
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $staging, $zipCesta,
    [System.IO.Compression.CompressionLevel]::Optimal,
    $false)     # bez vrchneho priecinka - appka rozbaluje priamo do seba
$sha = (Get-FileHash $zipCesta -Algorithm SHA256).Hash.ToLower()

$pocet = (Get-ChildItem $staging -Recurse -File).Count
Write-Host ""
Write-Host "  appka    : Metal Music Player (Windows)"
Write-Host "  verzia   : $verzia ($kod)"
Write-Host "  balik    : $zipMeno  ($pocet suborov, $('{0:N0} kB' -f ((Get-Item $zipCesta).Length / 1KB)))"
Write-Host "  sha256   : $sha"
Write-Host "  ciel     : \\$NasHost\$Share\$CielDirName\"
if ($Poznamka) { Write-Host "  poznamka : $Poznamka" }
else { Write-Host "  poznamka : (ziadna - appka ju neukaze)" -ForegroundColor DarkGray }
Write-Host ""

if ($Skus) {
    Write-Host "  (-Skus: nic som nezapisal)" -ForegroundColor Yellow
    Write-Host "  obsah balika:" -ForegroundColor DarkGray
    Get-ChildItem $staging -Recurse -File |
        ForEach-Object { Write-Host ("    " + $_.FullName.Substring($staging.Length + 1)) -ForegroundColor DarkGray }
    Remove-Item $docasny -Recurse -Force
    return
}

# --- nahrat ------------------------------------------------------------------
if (-not (Test-Path $CredFile)) {
    throw "Chyba $CredFile - bez neho sa neda prihlasit na NAS."
}
$txt  = Get-Content $CredFile -Raw
$user = ([regex]::Match($txt, '(?m)^\s*NAS_USER\s*=\s*(.+?)\s*$')).Groups[1].Value
$pass = ([regex]::Match($txt, '(?m)^\s*NAS_PASS\s*=\s*(.+?)\s*$')).Groups[1].Value
if (-not $user) { throw "V $CredFile chyba riadok NAS_USER=..." }

$unc = "\\$NasHost\$Share"
net.exe use $unc $pass /user:$user | Out-Null
$cielDir = Join-Path $unc $CielDirName

try {
    if (-not (Test-Path $cielDir)) { New-Item -ItemType Directory -Path $cielDir | Out-Null }

    # --- poistka proti nahratiu starsieho balika ----------------------------
    $nasManifest = Join-Path $cielDir 'latest.json'
    if ((Test-Path $nasManifest) -and -not $AjStarsiu) {
        $naNas = Get-Content $nasManifest -Raw | ConvertFrom-Json
        if ([int]$naNas.versionCode -gt $kod) {
            throw ("Na NAS-e uz je NOVSIA verzia $($naNas.versionName) " +
                   "($($naNas.versionCode)), nahravas $verzia ($kod). " +
                   "Ak to naozaj chces vratit spat, pridaj -AjStarsiu.")
        }
        if ([int]$naNas.versionCode -eq $kod) {
            throw ("Na NAS-e uz je verzia $($naNas.versionName) " +
                   "($($naNas.versionCode)). Zvys __version_code__ v " +
                   "music_player\__init__.py, inak si druhy notebook novu " +
                   "verziu nikdy nevypyta.")
        }
    }

    Copy-Item $zipCesta -Destination (Join-Path $cielDir $zipMeno) -Force
    Write-Host "  [OK] $zipMeno" -ForegroundColor Green

    # latest.json musi byt UTF-8 BEZ BOM. `Set-Content -Encoding utf8`
    # v PowerShelli 5.1 BOM pridava; presne na tom sa 31. 8. 2026 zaseklo
    # vydanie androidoveho playera. Windowsova appka BOM zniesla (cita cez
    # utf-8-sig), ale format nech je rovnaky ako v Player\.
    $manifest = [ordered]@{
        versionCode = $kod
        versionName = "$verzia"
        zip         = $zipMeno
        sha256      = $sha
        notes       = $Poznamka
        date        = (Get-Date -Format 'yyyy-MM-dd')
    } | ConvertTo-Json
    $tmp = Join-Path $docasny 'latest.json'
    [System.IO.File]::WriteAllText(
        $tmp, $manifest, (New-Object System.Text.UTF8Encoding($false)))
    Copy-Item $tmp -Destination (Join-Path $cielDir 'latest.json') -Force
    Write-Host "  [OK] latest.json (sha256 overi appka pred instalaciou)" -ForegroundColor Green

    # --- veci okolo balika ---------------------------------------------------
    # Instalator a README su na NAS-e preto, aby sa dal cisty notebook rozbehnut
    # bez tohto stromu - dvojklikom priamo zo sietoveho priecinka.
    $nasZdroj = Join-Path $Projekt 'nas'
    Get-ChildItem $nasZdroj -File | ForEach-Object {
        Copy-Item $_.FullName -Destination (Join-Path $cielDir $_.Name) -Force
        Write-Host "  [OK] $($_.Name)" -ForegroundColor Green
    }

    # Konfiguracia zvlast a rozbalena: v balicku je zabalena a clovek sa na nu
    # potrebuje pozriet aj z druheho stroja bez rozbalovania.
    $konfDir = Join-Path $cielDir 'konfiguracia'
    if (-not (Test-Path $konfDir)) { New-Item -ItemType Directory -Path $konfDir | Out-Null }
    foreach ($k in @('config.txt', 'spanok.m3u', 'spanok2.m3u')) {
        $zdroj = Join-Path $Projekt $k
        if (Test-Path $zdroj) {
            Copy-Item $zdroj -Destination (Join-Path $konfDir $k) -Force
            Write-Host "  [OK] konfiguracia\$k" -ForegroundColor Green
        }
    }

    # Meno balika nesie verziu, takze sa stare kusy neprepisu a priecinok by
    # rastol donekonecna. Appka aj tak vzdy instaluje to, na co ukazuje
    # latest.json.
    Get-ChildItem $cielDir -Filter 'metalmusic-pc-*.zip' -File |
        Where-Object { $_.Name -ne $zipMeno } |
        ForEach-Object {
            Remove-Item $_.FullName -Force
            Write-Host "  [-]  zmazane starsie: $($_.Name)" -ForegroundColor DarkGray
        }

    Write-Host ""
    Write-Host "  Hotovo. Druhy notebook si verziu $verzia ($kod) vypyta sam pri" -ForegroundColor Green
    Write-Host "  najblizsom spusteni prehravaca." -ForegroundColor Green
}
catch {
    Write-Host "  [CHYBA] $($_.Exception.Message)" -ForegroundColor Red
    if ($_.Exception.Message -match 'denied|odopret|prístup|pristup|UnauthorizedAccess') {
        Write-Host ""
        Write-Host "  Ucet '$user' zrejme nema zapis do $CielDirName." -ForegroundColor Yellow
        Write-Host "  DSM -> Control Panel -> Shared Folder -> Android -> Edit -> Permissions." -ForegroundColor Yellow
    }
    throw
}
finally {
    net.exe use $unc /delete /y | Out-Null
    Remove-Item $docasny -Recurse -Force -ErrorAction SilentlyContinue
}
