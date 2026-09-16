@echo off
REM Spusta hudba-po-zobudeni.ps1 - vsetka logika je tam.
REM Samostatny .cmd je tu preto, aby stacil dvojklik; .ps1 sa dvojklikom
REM na Windowse otvori v editore a nie spusti.
REM Prava spravcu netreba - uloha sa zaklada pod prihlasenym uzivatelom.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0hudba-po-zobudeni.ps1"
pause
