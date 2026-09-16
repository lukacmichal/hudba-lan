@echo off
rem Spusti Metal Music Player nezavisle od toho, kde priecinok lezi.
rem %~dp0 je priecinok tohto suboru, takze presun aj iny notebook prezije.
cd /d "%~dp0"

rem 1) pyw.exe - Python launcher pre okenne aplikacie (bez konzoly)
where pyw >nul 2>&1
if not errorlevel 1 (
    start "" pyw app.pyw
    exit /b 0
)

rem 2) pythonw.exe z PATH
where pythonw >nul 2>&1
if not errorlevel 1 (
    start "" pythonw app.pyw
    exit /b 0
)

rem 3) bezna per-user instalacia Pythonu
for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if exist "%%d\pythonw.exe" (
        start "" "%%d\pythonw.exe" app.pyw
        exit /b 0
    )
)

echo.
echo Python sa nenasiel. Nainstaluj ho z https://www.python.org/downloads/
echo a pri instalacii zaskrtni "Add python.exe to PATH".
echo.
echo Potom este raz: python -m pip install PySide6 mutagen requests
echo.
pause
exit /b 1
