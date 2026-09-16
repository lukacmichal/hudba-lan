@echo off
REM ---------------------------------------------------------------------------
REM Nainstaluje Metal Music Player (windowsovy prehravac) na tento pocitac
REM z tohto priecinka na NAS-e.
REM
REM Dvojklik staci - .ps1 sa dvojklikom otvori v editore a nie spusti, preto
REM je tu tento .cmd. Prava spravcu netreba.
REM
REM Aktualizacie uz potom riesi appka sama: pri kazdom spusteni sa pozrie
REM sem, a ked je tu novsia verzia, opyta sa.
REM ---------------------------------------------------------------------------
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0nainstaluj.ps1" %*
pause
