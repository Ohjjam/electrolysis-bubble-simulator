@echo off
setlocal
title Bubble Simulator (HER/OER electrolysis)

rem --- this .bat lives in the gen-2 folder ("2...") inside the project root.
rem     Sibling folders may have non-ASCII (Korean) names, so we resolve them
rem     from the filesystem with wildcards instead of typing them.
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"
if not exist "%HERE%\server_app.py" goto noproj
for %%I in ("%HERE%\..") do set "ROOT=%%~fI"
set "GEN1="
for /d %%D in ("%ROOT%\1*") do set "GEN1=%%D"

rem --- Python 3.14 (the one with the dependencies); fall back to PATH python ---
set "PYEXE=%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"

rem run from the project root so the interactive console can import bubblesim
cd /d "%ROOT%"

:menu
cls
echo ============================================================
echo    Bubble Simulator  -  HER / OER water electrolysis
echo ============================================================
echo    Project: %ROOT%
echo    Python : %PYEXE%
echo ------------------------------------------------------------
echo    [1]  LIVE MULTIPHYSICS APP  (gen 2 - Python kernel + browser)
echo         sliders: catalyst j0 / ECSA / membrane R / thermal / pH ...
echo    [2]  Classic web app        (gen 1 - legacy lumped model, JS only)
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
"%PYEXE%" "%HERE%\server_app.py"
goto menu

:web
start "" "%GEN1%\index.html"
goto menu

:demo
cls
"%PYEXE%" "%GEN1%\demo_multiphysics.py"
echo.
pause
goto menu

:figures
cls
echo Generating figures (this may take a little while)...
"%PYEXE%" "%GEN1%\run_demo.py"
echo.
echo Done. The PNGs are in the "outputs" folder inside the gen-1 folder.
pause
goto menu

:tests
cls
"%PYEXE%" "%ROOT%\tests\test_physics.py"
"%PYEXE%" "%ROOT%\tests\test_characterization.py"
"%PYEXE%" "%ROOT%\tests\test_two_electrode.py"
"%PYEXE%" "%ROOT%\tests\test_transport.py"
"%PYEXE%" "%ROOT%\tests\test_chemistry.py"
"%PYEXE%" "%ROOT%\tests\test_energy.py"
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
"%PYEXE%" -m pip install -r "%ROOT%\requirements.txt"
echo.
pause
goto menu

:noproj
echo.
echo  [!] server_app.py was not found next to this .bat.
echo      Keep this .bat inside the gen-2 folder ("2...") of the
echo      "Bubble simulator" project.
echo.
pause

:end
endlocal
