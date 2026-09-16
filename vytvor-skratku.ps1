# Vytvori/obnovi skratku na Metal Music Player podla aktualneho umiestnenia
# priecinka. Skratka ukazuje na spustit.cmd, ktory si Python najde sam.
param(
    [Parameter(Position = 0)]
    [string]$Kam = ""
)

$ErrorActionPreference = "Stop"
$projekt = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $projekt "spustit.cmd"
$ikona = Join-Path $projekt "music_player\icon.ico"

if (-not (Test-Path $launcher)) {
    Write-Host "Nenasiel som spustit.cmd v $projekt" -ForegroundColor Red
    exit 1
}

$ciele = @(Join-Path $projekt "Metal Music Player.lnk")
if ($Kam -eq "plocha") {
    $ciele += Join-Path ([Environment]::GetFolderPath("Desktop")) "Metal Music Player.lnk"
}

$shell = New-Object -ComObject WScript.Shell
foreach ($cesta in $ciele) {
    $lnk = $shell.CreateShortcut($cesta)
    $lnk.TargetPath = $launcher
    $lnk.WorkingDirectory = $projekt
    $lnk.Description = "Metal Music Player"
    $lnk.WindowStyle = 7          # spustit minimalizovane, konzola len blikne
    if (Test-Path $ikona) { $lnk.IconLocation = $ikona }
    $lnk.Save()
    Write-Host "Skratka: $cesta" -ForegroundColor Green
}

Write-Host "Ukazuje na: $launcher"
