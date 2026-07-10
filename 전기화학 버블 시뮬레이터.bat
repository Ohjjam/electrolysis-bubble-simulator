@echo off
setlocal
title Bubble Simulator (HER/OER electrolysis)

rem --- locate the project next to this .bat. The parent folder may be non-ASCII
rem     (Korean), so we derive its real path from the filesystem instead of typing it.
set "PROJ="
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"
if exist "%HERE%\server_app.py" set "PROJ=%HERE%"
if not defined PROJ for /d %%D in ("%~dp0_*") do if exist "%%D\Bubble simulator\server_app.py" set "PROJ=%%D\Bubble simulator"
if not defined PROJ if exist "%~dp0Bubble simulator\server_app.py" set "PROJ=%~dp0Bubble simulator"
if not defined PROJ goto noproj

rem --- Python 3.14 (the one with the dependencies); fall back to PATH python ---
set "PYEXE=%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"

cd /d "%PROJ%"

:menu
cls
echo ============================================================
echo    Bubble Simulator  -  HER / OER water electrolysis
echo ============================================================
echo    Project: %PROJ%
echo    Python : %PYEXE%
echo ------------------------------------------------------------
echo    [1]  LIVE MULTIPHYSICS APP  (NEW - Python kernel + browser)
echo         sliders: catalyst j0 / ECSA / membrane R / thermal / pH ...
echo    [2]  Classic web app        (legacy lumped model, JS only)
echo    [3]  Multiphysics text demo (numbers only)
echo    [4]  Generate 4 figures     (run_demo.py - outputs folder)
echo    [5]  Run all physics tests (38)
echo    [6]  Python console
echo    [7]  Install dependencies (matplotlib)
echo    [0]  Quit
echo.
set /p "choice=Select a number, then Enter: "

if "%choice%"=="1" goto app
if "%choice%"=="2" goto web
if "%choice%"=="3" goto demo
if "%choice%"=="4" goto figures
if "%choice%"=="5" goto tests
if "%choice%"=="6" goto console
if "%choice%"=="7" goto install
if "%choice%"=="0" goto end
goto menu

:app
cls
echo Starting the live multiphysics app (real Python kernel)...
echo The browser opens automatically. KEEP THIS WINDOW OPEN while using it.
echo Press Ctrl+C here (or close the window) to stop the app.
echo.
"%PYEXE%" "%PROJ%\server_app.py"
goto menu

:web
start "" "%PROJ%\index.html"
goto menu

:demo
cls
"%PYEXE%" "%PROJ%\demo_multiphysics.py"
echo.
pause
goto menu

:figures
cls
echo Generating figures (this may take a little while)...
"%PYEXE%" "%PROJ%\run_demo.py"
echo.
echo Done. Open the "outputs" folder to see the PNGs.
pause
goto menu

:tests
cls
"%PYEXE%" "%PROJ%\tests\test_physics.py"
"%PYEXE%" "%PROJ%\tests\test_characterization.py"
"%PYEXE%" "%PROJ%\tests\test_two_electrode.py"
"%PYEXE%" "%PROJ%\tests\test_transport.py"
"%PYEXE%" "%PROJ%\tests\test_chemistry.py"
"%PYEXE%" "%PROJ%\tests\test_energy.py"
echo.
pause
goto menu

:console
cls
echo Example:
echo   from bubblesim import Simulator, Operating
echo   h = Simulator(Operating(V_cell=2.0, model="two_electrode", thermal=True)).run(1.0, 2e-4)
echo   print(h["j"][-1], h["T"][-1])
echo.
echo (type  exit()  then Enter to return to the menu)
echo.
"%PYEXE%"
goto menu

:install
cls
"%PYEXE%" -m pip install -r "%PROJ%\requirements.txt"
echo.
pause
goto menu

:noproj
echo.
echo  [!] Could not find the project folder next to this .bat.
echo      Keep this .bat on the Desktop, beside the project folder
echo      (the one whose name starts with "_" containing "Bubble simulator").
echo.
pause

:end
endlocal
