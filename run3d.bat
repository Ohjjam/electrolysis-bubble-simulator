@echo off
REM ============================================================
REM  Launch the 3-D electrochemistry cell simulator app.
REM  Track A (cell-scale, live) + Track B (pore-scale, playback).
REM  Double-click to start the server and open the browser.
REM ============================================================
cd /d "%~dp0"
set "PY=C:\Users\user\AppData\Local\Python\pythoncore-3.14-64\python.exe"

echo Starting the 3-D app on http://localhost:8766/ ...
"%PY%" server3d_app.py
pause
