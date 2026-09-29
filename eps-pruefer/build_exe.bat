@echo off
rem Erstellt eine eigenstaendige EPS-Pruefer.exe (ohne Python-Installation lauffaehig).
rem Ghostscript muss auf dem Zielrechner trotzdem installiert sein.
cd /d "%~dp0"
py -3 -m pip install --upgrade pyinstaller || goto :fehler
py -3 -m PyInstaller --noconfirm --onefile --windowed --name EPS-Pruefer ^
    --collect-submodules eps_pruefer eps_pruefer_start.py || goto :fehler
echo.
echo Fertig: dist\EPS-Pruefer.exe
pause
goto :eof
:fehler
echo Build fehlgeschlagen.
pause
