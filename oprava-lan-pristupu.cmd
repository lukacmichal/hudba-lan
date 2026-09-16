@echo off
REM ---------------------------------------------------------------------------
REM Oprava LAN pristupu k prehravacu po zmene IP / po prechode na kabel.
REM
REM SPUSTIT NA TOM NOTEBOOKU, KDE BEZI PREHRAVAC (ten s 192.168.1.50).
REM Na druhom stroji to nema zmysel.
REM
REM Co sa stalo: prehravac vysiela UDP beacon (port 8766) a ten chodi - odchadzajuce
REM pakety firewall neriesi. Ale telefon sa potom pokusi otvorit http://<ip>:8765/health
REM a TO uz je PRICHODZIE spojenie. Ked Windows po zmene IP vyhodnoti siet ako novu,
REM da jej profil "Verejna" a stare vynimky (spravene pre "Sukromnu" Wi-Fi siet)
REM na nu neplatia. Vysledok: appka server "vidi" v beacone, ale nedovola sa mu.
REM
REM Preto sa tu robia DVE veci naraz:
REM   1. aktivna siet sa oznaci ako Sukromna (tam patri domaca LAN)
REM   2. vynimky sa spravia pre VSETKY profily (profile=any), aby uz zmena
REM      profilu ani prechod Wi-Fi <-> kabel nic nerozbil
REM
REM Tretia vec: vypne sa vyzadovanie hesla pri zobudeni zo spanku.
REM
REM Vypis je zamerne bez diakritiky - konzola je cp1250.
REM ---------------------------------------------------------------------------
setlocal

net session >nul 2>&1
if errorlevel 1 (
    echo.
    echo    Potrebujem prava spravcu - vypytam si ich...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b 0
)

echo.
echo    ============================================
echo      Oprava LAN pristupu k prehravacu
echo    ============================================
echo.

echo    [1/3] Oznacujem aktivne siete ako Sukromne...
powershell -NoProfile -Command "Get-NetConnectionProfile | Where-Object { $_.IPv4Connectivity -ne 'Disconnected' -and $_.InterfaceAlias -notmatch 'Tailscale' } | ForEach-Object { Write-Host ('        ' + $_.InterfaceAlias + ' (' + $_.Name + '): ' + $_.NetworkCategory + ' -> Private'); Set-NetConnectionProfile -InterfaceIndex $_.InterfaceIndex -NetworkCategory Private }"

echo.
echo    [2/3] Vynimky vo firewalle pre vsetky profily...
netsh advfirewall firewall delete rule name="Metal Music Player - API 8765" >nul 2>&1
netsh advfirewall firewall delete rule name="Metal Music Player - beacon 8766 (von)" >nul 2>&1
netsh advfirewall firewall delete rule name="Metal Music Player - beacon 8766 (dnu)" >nul 2>&1
netsh advfirewall firewall add rule name="Metal Music Player - API 8765" dir=in action=allow protocol=TCP localport=8765 profile=any >nul
if errorlevel 1 (echo         CHYBA pri pravidle 8765) else (echo         TCP 8765 dnu  - hotovo)
netsh advfirewall firewall add rule name="Metal Music Player - beacon 8766 (von)" dir=out action=allow protocol=UDP remoteport=8766 profile=any >nul
if errorlevel 1 (echo         CHYBA pri pravidle 8766 von) else (echo         UDP 8766 von  - hotovo)
netsh advfirewall firewall add rule name="Metal Music Player - beacon 8766 (dnu)" dir=in action=allow protocol=UDP localport=8766 profile=any >nul
if errorlevel 1 (echo         CHYBA pri pravidle 8766 dnu) else (echo         UDP 8766 dnu  - hotovo)

echo.
echo    [3/3] Vypinam heslo pri zobudeni zo spanku...
REM CONSOLELOCK je v nastaveniach napajania skryty, treba ho najprv odkryt.
powercfg -attributes SUB_NONE 0e796bdb-100d-47d6-a2d5-f7d2daa51f51 -ATTRIB_HIDE >nul 2>&1
powercfg -SETACVALUEINDEX SCHEME_CURRENT SUB_NONE CONSOLELOCK 0 >nul 2>&1
powercfg -SETDCVALUEINDEX SCHEME_CURRENT SUB_NONE CONSOLELOCK 0 >nul 2>&1
powercfg -SETACTIVE SCHEME_CURRENT >nul 2>&1
echo         hotovo (na sieti aj na baterke)

echo.
echo    ============================================
echo      Kontrola
echo    ============================================
powershell -NoProfile -Command "Get-NetConnectionProfile | Select-Object InterfaceAlias,Name,NetworkCategory | Format-Table -AutoSize"
powershell -NoProfile -Command "Get-NetFirewallRule -DisplayName 'Metal Music Player*' | Select-Object DisplayName,Direction,Action,Profile,Enabled | Format-Table -AutoSize"
powershell -NoProfile -Command "$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.|100\.)' } | Select-Object -First 1).IPAddress; Write-Host ''; Write-Host ('    Tento pocitac ma na LAN adresu: ' + $ip); Write-Host ('    Prehravac ma teda byt na:       http://' + $ip + ':8765/health')"

echo.
echo    Ak prehravac prave bezi, skus si to v prehliadaci na telefone.
echo    Ked to vypise {"status": "ok"}, cesta je priechodna a appka ho najde.
echo.
pause
