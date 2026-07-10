@echo off
setlocal
rem ---- start the 3-D cell simulator server (hidden) and open the 2-D panel view
set "PROJ="
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"
if exist "%HERE%\server3d_app.py" set "PROJ=%HERE%"
if not defined PROJ for /d %%D in ("%~dp0_*") do if exist "%%D\Bubble simulator\server3d_app.py" set "PROJ=%%D\Bubble simulator"
if not defined PROJ (echo project folder not found & pause & exit /b 1)
set "PYW=%LOCALAPPDATA%\Python\pythoncore-3.14-64\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
rem starts hidden; if already running the server just opens the link and exits
start "" "%PYW%" "%PROJ%\server3d_app.py" --no-browser
rem give it a moment to bind the port, then open the browser
timeout /t 2 >nul
start "" "http://localhost:8766/2d"
exit /b 0
