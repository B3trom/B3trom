@echo off
rem Kommandozeilen-Pruefung, z. B.:  pruefen_cli.bat "D:\Anzeigen" --html bericht.html
cd /d "%~dp0"
py -3 -m eps_pruefer --cli %*
