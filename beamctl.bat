@echo off
rem Lanceur Windows : double-clic pour demarrer beamctl.
setlocal
cd /d "%~dp0"

set PYTHON=py
where py >nul 2>nul || set PYTHON=python

%PYTHON% -m beamctl --output usb --open %*

echo.
echo beamctl s'est arrete.
pause
