@echo off
REM ---------------------------------------------------------------------------
REM Spusti Metal Music Player, ak este nebezi. Nic viac.
REM
REM Vola to naplanovana uloha "Hudba po zobudeni" - preto sa tu nic nepyta
REM a nic sa nepauzuje. Volat sa to da aj rucne, nic sa nepokazi: ked appka
REM uz bezi, skript len skonci.
REM
REM Cakanie na siet: po zobudeni ma Windows adaptery este dole. Bez neho by
REM sa beacon rozbehol s adresou, ktora o par sekund uz neplati.
REM
REM Vypis bez diakritiky - z planovaca ide do rury a konzola je cp1250.
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

powershell -NoProfile -NonInteractive -Command ^
  "$bezi = Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object { $_.CommandLine -match 'app\.pyw' }; if ($bezi) { exit 1 } else { exit 0 }"
if errorlevel 1 (
    echo Prehravac uz bezi - nechavam ho tak.
    exit /b 0
)

echo Cakam na siet...
powershell -NoProfile -NonInteractive -Command ^
  "for ($i = 0; $i -lt 30; $i++) { $ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.|100\.)' }; if ($ip) { Write-Host ('Siet je hore: ' + ($ip.IPAddress -join ', ')); exit 0 }; Start-Sleep -Seconds 2 }; Write-Host 'Siet nenabehla za 60 sekund - spustam aj tak.'"

echo Spustam prehravac...
call "%~dp0spustit.cmd"
exit /b 0
