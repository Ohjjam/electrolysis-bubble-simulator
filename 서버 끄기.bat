@echo off
setlocal
set "PROJ="
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"
if exist "%HERE%\server_stop.py" set "PROJ=%HERE%"
if not defined PROJ for /d %%D in ("%~dp0_*") do if exist "%%D\Bubble simulator\server_stop.py" set "PROJ=%%D\Bubble simulator"
if not defined PROJ (echo project folder not found & pause & exit /b 1)
set "PY=%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%PROJ%\server_stop.py"
taskkill /F /IM cloudflared.exe >nul 2>&1
taskkill /F /IM ngrok.exe >nul 2>&1
echo (tunnel stopped too, if it was running)
timeout /t 2 >nul
exit /b 0
