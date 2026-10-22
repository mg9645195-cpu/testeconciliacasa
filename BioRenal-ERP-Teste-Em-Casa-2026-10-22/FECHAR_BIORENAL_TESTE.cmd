@echo off
cd /d "%~dp0"
start "" "%~dp0runtime\pythonw.exe" "%~dp0launcher_segundo_plano.py" stop
exit /b
