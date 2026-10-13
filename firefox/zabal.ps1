<#
.SYNOPSIS
  Zabali rozsirenia pre Firefox do .xpi, s -Podpisat ich aj podpise u Mozilly.

.DESCRIPTION
  Su to dve casti:
    hlavne rozsirenie  (tento priecinok)  okienko s ovladanim + pozadie, ktore
                                          drzi prehravac najdeny
    styri tlacidla     (tlacidla\)        ⏮ ⏯ ⏭ 🔇 do listy — Firefox da jednemu
                                          rozsireniu len jedno tlacidlo, preto
                                          kazde zvlast; vyrabaju sa z
                                          tlacidla\varianty.json + tlacidlo.js

  Bezny Firefox nainstaluje natrvalo LEN podpisane rozsirenie. Nepodpisane
  sa da nahrat iba docasne (about:debugging -> "Nacitat docasny doplnok").

  Podpis je zadarmo a rozsirenie pri nom NEJDE do katalogu (kanal "unlisted"
  = len pre seba). Treba ucet na addons.mozilla.org a API kluce
  (https://addons.mozilla.org/developers/addon/api/key/) v
  C:\NAS\amo-credentials.local:
      AMO_JWT_ISSUER=user:12345:678
      AMO_JWT_SECRET=...

  Podpisane .xpi idu na NAS (\\nas.local\Android\PlayerPC\firefox),
  odkial sa instaluju na oboch notebookoch: Firefox -> Ctrl+O -> subor.

  Mozilla tu istu verziu druhy raz nepodpise. Ked sa zmeni hlavne rozsirenie,
  zvys "version" v manifest.json; ked tlacidla, "verzia" vo varianty.json.
  Co uz podpisane v dist\ lezi, sa preskoci.

.PARAMETER Podpisat
  Okrem zabalenia aj podpisat cez web-ext sign a nahrat na NAS.

.EXAMPLE
  .\zabal.ps1
  .\zabal.ps1 -Podpisat
#>
[CmdletBinding()]
param([switch]$Podpisat)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$Zdroj = $PSScriptRoot
$Dist = Join-Path $Zdroj 'dist'
$Utf8 = New-Object System.Text.UTF8Encoding $false
New-Item -ItemType Directory -Force $Dist | Out-Null

# ── zoznam balikov ───────────────────────────────────────────────────────────
$hlavnyManifest = Get-Content (Join-Path $Zdroj 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$baliky = @(
    [pscustomobject]@{
        meno    = 'metalmusic-firefox'
        id      = $hlavnyManifest.browser_specific_settings.gecko.id
        verzia  = $hlavnyManifest.version
        zdroj   = $Zdroj
        # web-ext pise zip s lomkami "/", ako ich Firefox chce; Compress-Archive
        # v PowerShelli 5.1 by zapisal "\" a Firefox by .xpi odmietol.
        ignoruj = @('zabal.ps1', 'amo_stiahni.py', 'README.md', 'NAVOD.txt', 'dist', 'dist/**', 'tlacidla', 'tlacidla/**')
    }
)

$varianty = Get-Content (Join-Path $Zdroj 'tlacidla\varianty.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$pozadieJs = Get-Content (Join-Path $Zdroj 'pozadie.js') -Raw -Encoding UTF8
foreach ($v in $varianty.tlacidla) {
    # Pozadie prijima spravy len od tlacidiel, ktore pozna po mene.
    if ($pozadieJs -notmatch [regex]::Escape('"' + $v.id + '"')) {
        throw "Tlacidlo $($v.id) chyba v zozname TLACIDLA v pozadie.js."
    }
    $ciel = Join-Path $Dist ('tlacidla\' + $v.akcia)
    if (Test-Path $ciel) { Remove-Item -Recurse -Force $ciel }
    New-Item -ItemType Directory -Force (Join-Path $ciel 'ikony') | Out-Null
    Copy-Item (Join-Path $Zdroj 'tlacidla\tlacidlo.js') $ciel
    foreach ($ik in $v.ikony) {
        Copy-Item (Join-Path $Zdroj "tlacidla\ikony\$ik-*.png") (Join-Path $ciel 'ikony')
    }
    $konfig = 'const TLACIDLO = ' + (@{ akcia = $v.akcia; ikony = @($v.ikony); titul = $v.titul } |
              ConvertTo-Json -Compress) + ';'
    [IO.File]::WriteAllText((Join-Path $ciel 'konfig.js'),
        "// Vyrobene skriptom zabal.ps1 z varianty.json - needitovat.`n$konfig`n", $Utf8)
    $prva = $v.ikony[0]
    $manifest = [ordered]@{
        manifest_version = 2
        name             = $v.nazov
        version          = $varianty.verzia
        description      = "Tlačidlo do lišty Firefoxu pre Metal Music Player (hudba-lan): $($v.titul). Potrebuje hlavné rozšírenie Metal Music Player."
        icons            = [ordered]@{ '48' = "ikony/$prva-48.png"; '96' = "ikony/$prva-96.png" }
        browser_action   = [ordered]@{
            default_icon  = [ordered]@{ '16' = "ikony/$prva-16.png"; '32' = "ikony/$prva-32.png" }
            default_title = $v.titul
            # Rovno do listy, nie do ponuky rozsireni (puzzle).
            default_area  = 'navbar'
        }
        background       = [ordered]@{ scripts = @('konfig.js', 'tlacidlo.js') }
        browser_specific_settings = [ordered]@{
            gecko = [ordered]@{
                id                 = $v.id
                strict_min_version = '142.0'
                data_collection_permissions = [ordered]@{ required = @('none') }
            }
        }
    }
    [IO.File]::WriteAllText((Join-Path $ciel 'manifest.json'), ($manifest | ConvertTo-Json -Depth 10), $Utf8)
    $baliky += [pscustomobject]@{
        meno    = 'mmp-tlacidlo-' + $v.akcia
        id      = $v.id
        verzia  = $varianty.verzia
        zdroj   = $ciel
        ignoruj = @()
    }
}

function Je-Podpisane($xpi) {
    if (-not (Test-Path $xpi)) { return $false }
    $zip = [IO.Compression.ZipFile]::OpenRead($xpi)
    try { return [bool]($zip.Entries | Where-Object { $_.FullName -eq 'META-INF/mozilla.rsa' }) }
    finally { $zip.Dispose() }
}

# ── len zabalit ──────────────────────────────────────────────────────────────
if (-not $Podpisat) {
    foreach ($b in $baliky) {
        $xpi = Join-Path $Dist "$($b.meno)-$($b.verzia).xpi"
        if (Je-Podpisane $xpi) { Write-Host "  $($b.meno) $($b.verzia): podpisane uz je, nechavam"; continue }
        $argumenty = @('--yes', 'web-ext@latest', 'build', '--source-dir', $b.zdroj, '--artifacts-dir', $Dist,
                       '--overwrite-dest', '--filename', "$($b.meno)-$($b.verzia).zip")
        if ($b.ignoruj) { $argumenty += '--ignore-files'; $argumenty += $b.ignoruj }
        & npx @argumenty | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "web-ext build zlyhal: $($b.meno)" }
        Move-Item -Force (Join-Path $Dist "$($b.meno)-$($b.verzia).zip") $xpi
        Write-Host "  nepodpisane: $xpi"
    }
    Write-Host ''
    Write-Host '  Bezny Firefox ich nahra len docasne (about:debugging). Natrvalo: -Podpisat.'
    return
}

# ── podpisat a nahrat ────────────────────────────────────────────────────────
$kluce = Join-Path (Split-Path (Split-Path $Zdroj)) 'amo-credentials.local'
if (-not (Test-Path $kluce)) {
    throw "Chyba $kluce s AMO_JWT_ISSUER a AMO_JWT_SECRET (viz popis skriptu)."
}
$hodnoty = @{}
foreach ($riadok in Get-Content $kluce -Encoding UTF8) {
    if ($riadok -match '^\s*([A-Z_]+)\s*=\s*(.+?)\s*$') { $hodnoty[$Matches[1]] = $Matches[2] }
}
if (-not $hodnoty['AMO_JWT_ISSUER'] -or -not $hodnoty['AMO_JWT_SECRET']) {
    throw "V $kluce chyba AMO_JWT_ISSUER alebo AMO_JWT_SECRET."
}

# Na NAS rovnako ako nahraj-pc-na-nas.ps1: share bez prihlasenia zapis neda.
$nasKluce = Join-Path (Split-Path (Split-Path $Zdroj)) 'nas-credentials.local'
$nasTxt = Get-Content $nasKluce -Raw
$nasUser = ([regex]::Match($nasTxt, '(?m)^\s*NAS_USER\s*=\s*(.+?)\s*$')).Groups[1].Value
$nasPass = ([regex]::Match($nasTxt, '(?m)^\s*NAS_PASS\s*=\s*(.+?)\s*$')).Groups[1].Value
net.exe use '\\nas.local\Android' $nasPass /user:$nasUser 2>$null | Out-Null
$cielNas = '\\nas.local\Android\PlayerPC\firefox'
New-Item -ItemType Directory -Force $cielNas | Out-Null

# Kluce idu cez premenne prostredia, nie cez prikazovy riadok — tam by ich
# videl kazdy, kto si pozrie zoznam procesov.
$env:WEB_EXT_API_KEY = $hodnoty['AMO_JWT_ISSUER']
$env:WEB_EXT_API_SECRET = $hodnoty['AMO_JWT_SECRET']
try {
    foreach ($b in $baliky) {
        $xpi = Join-Path $Dist "$($b.meno)-$($b.verzia).xpi"
        if (-not (Je-Podpisane $xpi)) {
            # Uz raz odoslana verzia sa podpisat znova neda — ked na AMO je,
            # stiahne sa (amo_stiahni.py: 0 stiahnute, 2 nie je, 3 caka).
            & python (Join-Path $Zdroj 'amo_stiahni.py') $b.id $b.verzia $xpi
            switch ($LASTEXITCODE) {
                0 { }
                2 { }
                3 { throw "$($b.meno) $($b.verzia) Mozilla este schvaluje - spusti skript o chvilu znova." }
                default { throw "amo_stiahni.py zlyhal pre $($b.meno)." }
            }
        }
        if (-not (Je-Podpisane $xpi)) {
            $docasne = Join-Path $Dist ('podpis-' + [guid]::NewGuid().ToString('N'))
            $argumenty = @('--yes', 'web-ext@latest', 'sign', '--channel', 'unlisted',
                           '--source-dir', $b.zdroj, '--artifacts-dir', $docasne)
            if ($b.ignoruj) { $argumenty += '--ignore-files'; $argumenty += $b.ignoruj }
            & npx @argumenty
            if ($LASTEXITCODE -ne 0) { throw "web-ext sign zlyhal: $($b.meno)" }
            # web-ext ho pomenuje podla interneho id u Mozilly (napr. 0be58c...-1.0.xpi).
            $stiahnute = Get-ChildItem $docasne -Filter '*.xpi' | Select-Object -First 1
            if (-not $stiahnute) { throw "Podpisane .xpi pre $($b.meno) neprislo." }
            Move-Item -Force $stiahnute.FullName $xpi
            Remove-Item -Recurse -Force $docasne
            if (-not (Je-Podpisane $xpi)) { throw "$xpi nema podpis." }
        } else {
            Write-Host "  $($b.meno) $($b.verzia): podpisane uz bolo"
        }
        Copy-Item -Force $xpi (Join-Path $cielNas (Split-Path $xpi -Leaf))
        Write-Host "  na NAS-e: $cielNas\$(Split-Path $xpi -Leaf)"
    }
} finally {
    Remove-Item Env:WEB_EXT_API_KEY, Env:WEB_EXT_API_SECRET -ErrorAction SilentlyContinue
}

# Navod lezi vedla .xpi — tam ho clovek hlada, ked instaluje na dalsom notebooku.
Copy-Item -Force (Join-Path $Zdroj 'NAVOD.txt') (Join-Path $cielNas 'NAVOD.txt')
Write-Host "  na NAS-e: $cielNas\NAVOD.txt"

# Stare verzie z NAS-u prec, nech sa omylom nenainstaluje predosla.
$platne = $baliky | ForEach-Object { "$($_.meno)-$($_.verzia).xpi" }
Get-ChildItem $cielNas -Filter '*.xpi' | Where-Object { $platne -notcontains $_.Name } | ForEach-Object {
    try {
        Remove-Item -Force $_.FullName -ErrorAction Stop
        Write-Host "  zmazane starsie: $($_.Name)"
    } catch {
        # Typicky ho ma prave otvoreny Firefox na druhom notebooku.
        Write-Host "  starsie $($_.Name) sa zmazat nedalo (je otvorene) - zmaze sa pri dalsom vydani"
    }
}
