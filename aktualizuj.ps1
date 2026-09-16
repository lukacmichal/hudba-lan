# ---------------------------------------------------------------------------
# Dokonci aktualizaciu prehravaca: pocka, kym sa appka ukonci, prekopiruje
# pripravene subory do instalacneho priecinka a appku zase spusti.
#
# Spusta to samotna appka (music_player\self_update.py) a NIE priamo clovek —
# ale spustit sa da aj rucne, ked sa update zasekol; parametre su v logu.
#
# Preco samostatny proces: appka nemoze prepisovat subory, z ktorych prave
# bezi. Ked by sa kopirovanie v polovici zaseklo, ostala by zmiesana z dvoch
# verzii — takto sa kopiruje az do ukonceneho prehravaca.
#
# Skript sa spusta z DOCASNEHO priecinka, nie z instalacneho: keby bezal
# odtial, kam kopiruje, prepisoval by sam seba.
#
# Vypis bez diakritiky - log sa cita v cp1250 konzole.
# ---------------------------------------------------------------------------
param(
    [Parameter(Mandatory)][int]$ProcesId,      # PID beziacej appky ($PID je rezervovane
                                               # meno, preto nie -Pid)
    [Parameter(Mandatory)][string]$Zdroj,      # rozbalena nova verzia (docasny priecinok)
    [Parameter(Mandatory)][string]$Ciel,       # instalacny priecinok appky
    [string]$Spustit = "",                     # co spustit po dokonceni (spustit.cmd)
    [string]$Log = ""
)

$ErrorActionPreference = 'Stop'

function Zapis([string]$text) {
    $riadok = "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $text
    Write-Host $riadok
    if ($Log) {
        try { Add-Content -Path $Log -Value $riadok -Encoding UTF8 } catch { }
    }
}

Zapis "--- aktualizacia zacina ---"
Zapis "zdroj = $Zdroj"
Zapis "ciel  = $Ciel"
Zapis "pid   = $ProcesId"

# --- 1) pockat na ukoncenie appky -------------------------------------------
# 60 sekund staci na ulozenie stavu aj na zatvorenie okna. Ked appka dovtedy
# neskonci (visi na dialogu), aktualizacia sa NEROBI - prepisat subory pod
# beziacim procesom je horsie nez ju odlozit na priste.
$cakal = $false
for ($i = 0; $i -lt 120; $i++) {
    $proces = Get-Process -Id $ProcesId -ErrorAction SilentlyContinue
    if (-not $proces) { $cakal = $true; break }
    Start-Sleep -Milliseconds 500
}
if (-not $cakal) {
    Zapis "CHYBA: appka (pid $ProcesId) sa za 60 s neukoncila - nic som neprepisal."
    exit 1
}
# Windows drzi subory este chvilu po skonceni procesu.
Start-Sleep -Milliseconds 500
Zapis "appka je ukoncena, kopirujem"

# --- 2) prekopirovat -----------------------------------------------------
# Chranene subory (config.txt, spankove zoznamy) uz zo $Zdroj vyhodila appka,
# takze sa tu kopiruje vsetko, co v nom ostalo.
try {
    if (-not (Test-Path $Ciel)) { New-Item -ItemType Directory -Path $Ciel -Force | Out-Null }
    Copy-Item -Path (Join-Path $Zdroj '*') -Destination $Ciel -Recurse -Force
    Zapis "subory su na mieste"
} catch {
    Zapis "CHYBA pri kopirovani: $($_.Exception.Message)"
    Zapis "Instalacia moze byt neuplna - spusti nainstaluj.cmd z NAS-u."
    exit 1
}

# --- 3) upratat po starej verzii --------------------------------------------
# Skompilovane .pyc zo starych modulov by ostali lezat; Python ich sice
# nepouzije, ale pri hladani chyby matu.
Get-ChildItem -Path $Ciel -Filter '__pycache__' -Recurse -Directory -ErrorAction SilentlyContinue |
    ForEach-Object {
        try { Remove-Item $_.FullName -Recurse -Force } catch { }
    }

# --- 4) spustit appku spat ---------------------------------------------------
if ($Spustit -and (Test-Path $Spustit)) {
    Zapis "spustam $Spustit"
    Start-Process -FilePath $Spustit -WorkingDirectory $Ciel -WindowStyle Hidden
} else {
    Zapis "spustac sa nenasiel ($Spustit) - appku spusti rucne"
}

# --- 5) zmazat docasne subory ------------------------------------------------
# Vlastny skript zmazat nemozeme (prave z neho bezime), zvysok ano.
try { Remove-Item $Zdroj -Recurse -Force } catch { }

Zapis "--- hotovo ---"
exit 0
