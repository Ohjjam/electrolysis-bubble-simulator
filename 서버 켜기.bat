@echo off
setlocal
set "PROJ="
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"
if exist "%HERE%\server_app.py" set "PROJ=%HERE%"
if not defined PROJ for /d %%D in ("%~dp0_*") do if exist "%%D\Bubble simulator\server_app.py" set "PROJ=%%D\Bubble simulator"
if not defined PROJ (echo project folder not found & pause & exit /b 1)
set "PYW=%LOCALAPPDATA%\Python\pythoncore-3.14-64\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
rem starts hidden; if already running it just opens the link
start "" "%PYW%" "%PROJ%\server_app.py"
exit /b 0
