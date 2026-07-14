@echo off
REM ==========================================================================
REM  Push local changes to the Ohjjam repo -> cloud server auto-updates ~2 min.
REM  (ASCII-only on purpose so the console never garbles.)
REM  NOTE: this commits ALL current changes in this folder, then pushes.
REM ==========================================================================
cd /d "%~dp0"
echo.
echo === Deploying: commit all changes + push to ohjam/main ===
git add -A
git commit -m "deploy update"
REM  the saved git credential is read-only; borrow the logged-in gh CLI for the push
git -c credential.helper= -c "credential.helper=!gh auth git-credential" push ohjam main
echo.
echo Done. The live server pulls the latest within about 2 minutes.
echo.
pause
