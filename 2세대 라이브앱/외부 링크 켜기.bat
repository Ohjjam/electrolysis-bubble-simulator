@echo off
setlocal
title Bubble Simulator - external link
set "PROJ="
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"
if exist "%HERE%\server_tunnel.py" set "PROJ=%HERE%"
if not defined PROJ for /d %%D in ("%~dp0_*") do if exist "%%D\Bubble simulator\server_tunnel.py" set "PROJ=%%D\Bubble simulator"
if not defined PROJ (echo project folder not found & pause & exit /b 1)
set "PY=%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%PROJ%\server_tunnel.py"
echo.
pause
exit /b 0
