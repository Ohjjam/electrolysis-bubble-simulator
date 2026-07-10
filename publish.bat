@echo off
REM ============================================================
REM  Publish the bubble simulator web app to GitHub Pages.
REM  Edit app.html or bubblesim\ , then just double-click this.
REM  (Rebuilds docs\ , commits, and pushes -> live in ~1 min.)
REM ============================================================
cd /d "%~dp0"
set "PY=C:\Users\user\AppData\Local\Python\pythoncore-3.14-64\python.exe"

echo [1/3] Building web app...
"%PY%" build_web.py || (echo BUILD FAILED & pause & exit /b 1)

echo [2/3] Committing...
git add -A -- docs app.html server_app.py sim_bridge.py build_web.py bubblesim README.md .gitignore
git commit -m "update web build"

echo [3/3] Pushing...
git push

echo.
echo Done. The live link refreshes in about a minute.
echo   https://ate0339-rgb.github.io/electrolysis-bubble-simulator/
pause
