@echo off
rem EPS-Pruefer starten. EPS-Dateien oder Ordner koennen auch auf diese Datei gezogen werden.
cd /d "%~dp0"
where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw -3 -m eps_pruefer %*
    goto :eof
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw -m eps_pruefer %*
    goto :eof
)
echo Python wurde nicht gefunden. Bitte Python 3.10 oder neuer von https://www.python.org installieren
echo (bei der Installation "Add python.exe to PATH" anhaken).
pause
