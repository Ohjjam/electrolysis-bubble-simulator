@echo off
setlocal
REM ============================================================
REM  Launch the 3-D electrochemistry cell simulator app.
REM  Track A (cell-scale, live) + Track B (pore-scale, playback).
REM  Double-click to start the server and open the browser.
REM ============================================================
cd /d "%~dp0"
set "PY_EXE="
set "PY_ARGS="

REM Prefer a project-local environment, then the Windows launcher.  Every
REM candidate must actually import NumPy before it is accepted.
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -c "import numpy" >nul 2>&1
  if not errorlevel 1 set "PY_EXE=%~dp0.venv\Scripts\python.exe"
)
if not defined PY_EXE (
  py -3.14 -c "import numpy" >nul 2>&1
  if not errorlevel 1 (
    set "PY_EXE=py"
    set "PY_ARGS=-3.14"
  )
)
if not defined PY_EXE if exist "%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe" (
  "%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe" -c "import numpy" >nul 2>&1
  if not errorlevel 1 set "PY_EXE=%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe"
)
if not defined PY_EXE (
  python -c "import numpy" >nul 2>&1
  if not errorlevel 1 set "PY_EXE=python"
)
if not defined PY_EXE (
  echo [ERROR] Python with NumPy was not found.
  echo Create .venv or install Python 3.14 and NumPy, then try again.
  pause
  exit /b 1
)

echo Starting the 3-D app on http://localhost:8766/ ...
"%PY_EXE%" %PY_ARGS% server3d_app.py --view 3d %*
pause
