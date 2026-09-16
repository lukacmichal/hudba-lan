@echo off
rem Vyrobi (alebo obnovi) skratku "Metal Music Player.lnk" podla toho,
rem kde prave lezi tento priecinok. Spusti po presune priecinka alebo
rem pri prvom nasadeni na dalsom notebooku.
rem Volitelny parameter: "plocha" = skratku daj aj na plochu.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0vytvor-skratku.ps1" %*
