# ---------------------------------------------------------------------------
# Prva instalacia windowsoveho prehravaca na novom pocitaci, priamo z NAS-u.
#
# Skript bezi Z NAS-u (lezi vedla latest.json a balika), takze na cielovom
# pocitaci netreba nic mat - staci sa dostat na \\nas.local\Android\PlayerPC
# a dvojkliknut nainstaluj.cmd.
#
# Dalsie verzie uz instaluje appka sama, tento skript sa spusta raz.
#
# Vypis bez diakritiky - konzola je cp1250.
# ---------------------------------------------------------------------------
param(
    # Kam sa ma appka nainstalovat. Bez neho sa skript opyta.
    [string]$Kam = "",
    # Bez pytania - pouzije sa predvoleny priecinok.
    [switch]$BezOtazok
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem

$Zdroj = $PSScriptRoot
$PredvolenyCiel = Join-Path $env:LOCALAPPDATA 'MetalMusicPlayer'

# Subory, ktore sa v uz existujucej instalacii NEPREPISU. Rovnaky zoznam ma
# music_player\self_update.py - ked sa meni, treba zmenit obe miesta.
$ChraneneMena = @('config.txt', 'spanok.m3u', 'spanok2.m3u')
$ChranenePripony = @('.lnk', '.local')

function Zapis([string]$text, [string]$farba = 'Gray') {
    Write-Host $text -ForegroundColor $farba
}

Write-Host ""
Zapis "  Metal Music Player - instalacia z NAS-u" 'Cyan'
Zapis "  zdroj: $Zdroj"
Write-Host ""

# --- 1) manifest -------------------------------------------------------------
$manifestCesta = Join-Path $Zdroj 'latest.json'
if (-not (Test-Path $manifestCesta)) {
    Zapis "  Nenasiel som latest.json v $Zdroj." 'Red'
    Zapis "  Novu verziu na NAS nahrava nahraj-pc-na-nas.ps1 z priecinka hudba-lan." 'Yellow'
    exit 1
}
$m = Get-Content $manifestCesta -Raw | ConvertFrom-Json
$balik = Join-Path $Zdroj $m.zip
if (-not (Test-Path $balik)) {
    Zapis "  latest.json ukazuje na $($m.zip), ale ten tu nie je." 'Red'
    exit 1
}
Zapis "  verzia: $($m.versionName) ($($m.versionCode)), balik $($m.zip)"
if ($m.notes) { Zapis "  co je nove: $($m.notes)" }

# --- 2) kam ------------------------------------------------------------------
if (-not $Kam) {
    if ($BezOtazok) {
        $Kam = $PredvolenyCiel
    } else {
        Write-Host ""
        Zapis "  Kam to nainstalovat? Enter = $PredvolenyCiel"
        $odpoved = Read-Host "  priecinok"
        $Kam = if ($odpoved.Trim()) { $odpoved.Trim() } else { $PredvolenyCiel }
    }
}
$Kam = [System.Environment]::ExpandEnvironmentVariables($Kam)
$uzTamJe = Test-Path (Join-Path $Kam 'app.pyw')
Write-Host ""
if ($uzTamJe) {
    Zapis "  V $Kam uz appka je - prepisem kod, tvoje nastavenia nechavam." 'Yellow'
} else {
    Zapis "  Instalujem do: $Kam"
}

# --- 3) overit balik ---------------------------------------------------------
# Rovnako ako appka: nesediaci sucet znamena neuplne skopirovany balik a taky
# sa neinstaluje.
$sha = (Get-FileHash $balik -Algorithm SHA256).Hash.ToLower()
if ($sha -ne ("" + $m.sha256).ToLower()) {
    Zapis "  Kontrolny sucet balika nesedi - je poskodeny alebo neuplny." 'Red'
    Zapis "  cakal som $($m.sha256)" 'DarkGray'
    Zapis "  prisiel   $sha" 'DarkGray'
    exit 1
}
Zapis "  kontrolny sucet sedi" 'DarkGray'

# --- 4) rozbalit a skopirovat ------------------------------------------------
$docasny = Join-Path $env:TEMP ("metalplayer-instalacia-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $docasny -Force | Out-Null
try {
    [System.IO.Compression.ZipFile]::ExtractToDirectory($balik, $docasny)

    # Osobne subory, ktore uz v instalacii su, z pripraveneho stromu vyhodime -
    # az potom sa kopiruje. Inak by prepis config.txt zmazal DeepL kluc aj
    # cestu k hudbe.
    $ponechane = @()
    Get-ChildItem $docasny -Recurse -File | ForEach-Object {
        $chraneny = ($ChraneneMena -contains $_.Name.ToLower()) -or
                    ($ChranenePripony -contains $_.Extension.ToLower())
        if (-not $chraneny) { return }
        $vCieli = Join-Path $Kam $_.FullName.Substring($docasny.Length + 1)
        if (Test-Path $vCieli) {
            Remove-Item $_.FullName -Force
            $ponechane += $_.Name
        }
    }

    if (-not (Test-Path $Kam)) { New-Item -ItemType Directory -Path $Kam -Force | Out-Null }
    Copy-Item -Path (Join-Path $docasny '*') -Destination $Kam -Recurse -Force
    Zapis "  subory su na mieste" 'Green'
    if ($ponechane) {
        Zapis "  nechavam tvoje: $(($ponechane | Sort-Object -Unique) -join ', ')" 'Green'
    }
}
finally {
    Remove-Item $docasny -Recurse -Force -ErrorAction SilentlyContinue
}

# --- 5) skratka --------------------------------------------------------------
# .lnk nesie absolutnu cestu, takze musi vzniknut az tu, na tomto pocitaci.
$skratka = Join-Path $Kam 'vytvor-skratku.cmd'
if (Test-Path $skratka) {
    & $skratka plocha | Out-Null
    Zapis "  skratka je na ploche" 'Green'
}

# --- 6) prihlasenie na NAS pre buduce aktualizacie ---------------------------
# Bez ulozeneho poverenia sa appka na tomto pocitaci na NAS nedostane a
# aktualizacie by TICHO nefungovali - co je presne ten druh poruchy, ktory sa
# odhali az o pol roka. Na pocitaci so zdrojakmi (C:\NAS) si heslo najde sama
# v nas-credentials.local, inde ho musi mat Windows.
$server = ([regex]::Match($Zdroj, '^\\\\([^\\]+)\\')).Groups[1].Value
if ($server) {
    $uzUlozene = (cmdkey /list:$server 2>$null | Select-String -Quiet 'Target:')
    $maSubor = (Test-Path (Join-Path $Kam 'nas-credentials.local')) -or
               (Test-Path 'nas-credentials.local')
    if ($uzUlozene -or $maSubor) {
        Write-Host ""
        Zapis "  Pristup na NAS je vybaveny - appka sa bude vediet aktualizovat." 'Green'
    } elseif ($BezOtazok) {
        Write-Host ""
        Zapis "  POZOR: k NAS-u ($server) nie je ulozene ziadne poverenie." 'Yellow'
        Zapis "  Bez neho sa appka nebude vediet aktualizovat. Doplnis to prikazom:" 'Yellow'
        Zapis "      cmdkey /add:$server /user:MENO /pass" 'Yellow'
    } else {
        Write-Host ""
        Zapis "  Aby sa appka vedela sama aktualizovat, Windows si musi zapamatat"
        Zapis "  prihlasenie na NAS ($server). Zada sa raz."
        $odpoved = Read-Host "  Ulozit teraz? (a/n)"
        if ($odpoved -match '^[aAyY]') {
            $meno = Read-Host "  meno (Enter = nasuser)"
            if (-not $meno.Trim()) { $meno = 'nasuser' }
            $tajne = Read-Host "  heslo" -AsSecureString
            $heslo = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
                [Runtime.InteropServices.Marshal]::SecureStringToBSTR($tajne))
            cmdkey /add:$server /user:$meno /pass:$heslo | Out-Null
            if ($LASTEXITCODE -eq 0) { Zapis "  poverenie je ulozene" 'Green' }
            else { Zapis "  cmdkey skoncil s chybou - aktualizacie nemusia fungovat" 'Yellow' }
            $heslo = $null
        } else {
            Zapis "  Preskocene. Appka sa bude spustat, ale aktualizacie ticho" 'Yellow'
            Zapis "  nepojdu, kym poverenie nedoplnis:" 'Yellow'
            Zapis "      cmdkey /add:$server /user:MENO /pass" 'Yellow'
        }
    }
}

# --- 7) Python ---------------------------------------------------------------
Write-Host ""
$python = $null
foreach ($meno in @('python', 'py')) {
    $najdeny = Get-Command $meno -ErrorAction SilentlyContinue
    if ($najdeny) { $python = $najdeny.Source; break }
}
if (-not $python) {
    Zapis "  Python na tomto pocitaci nie je." 'Yellow'
    Zapis "  Nainstaluj ho z https://www.python.org/downloads/ a zaskrtni" 'Yellow'
    Zapis "  'Add python.exe to PATH'. Potom este raz:" 'Yellow'
    Zapis "      python -m pip install PySide6 mutagen requests" 'Yellow'
} else {
    # Jedno spustenie Pythonu, ktore vypise mena chybajucich kniznic a vzdy
    # skonci uspesne. Volat `python -c "import X"` pre kazdu zvlast sa neda:
    # neuspesny import pise na stderr a PowerShell 5.1 z toho urobi
    # NativeCommandError, cim by instalator spadol prave vtedy, ked ma poradit.
    $ErrorActionPreference = 'Continue'
    $riadok = & $python -c "import importlib.util; print(' '.join(m for m in ('PySide6','mutagen','requests') if importlib.util.find_spec(m) is None))"
    $ErrorActionPreference = 'Stop'
    $chybaju = @($riadok -split '\s+' | Where-Object { $_ })
    if ($chybaju) {
        Zapis "  Chybaju kniznice: $($chybaju -join ', ')" 'Yellow'
        $doinstalovat = $BezOtazok
        if (-not $BezOtazok) {
            $odpoved = Read-Host "  Doinstalovat teraz? (a/n)"
            $doinstalovat = $odpoved -match '^[aAyY]'
        }
        if ($doinstalovat) {
            & $python -m pip install --disable-pip-version-check @chybaju
            if ($LASTEXITCODE -eq 0) { Zapis "  kniznice su nainstalovane" 'Green' }
            else { Zapis "  pip skoncil s chybou - dorob to rucne" 'Red' }
        } else {
            Zapis "  Rucne:  python -m pip install $($chybaju -join ' ')" 'Yellow'
        }
    } else {
        Zapis "  Python aj kniznice su v poriadku" 'Green'
    }
}

# --- 8) hotovo ---------------------------------------------------------------
Write-Host ""
Zapis "  Hotovo. Prehravac spustis skratkou na ploche alebo cez" 'Green'
Zapis "  $Kam\spustit.cmd" 'Green'
Write-Host ""
Zapis "  Dalsie verzie uz instalovat netreba - appka sa pri kazdom spusteni" 'DarkGray'
Zapis "  pozrie sem na NAS a novu verziu si vypyta sama." 'DarkGray'
Write-Host ""
