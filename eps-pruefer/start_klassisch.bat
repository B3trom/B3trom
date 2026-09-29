@echo off
rem Startet die klassische Oberflaeche (v1) des EPS-Pruefers.
cd /d "%~dp0"
where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw -3 -m eps_pruefer --klassisch %*
    goto :eof
)
start "" pythonw -m eps_pruefer --klassisch %*
