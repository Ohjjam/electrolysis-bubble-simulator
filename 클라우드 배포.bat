@echo off
REM ==========================================================================
REM  Deploy the Bubble Simulator to the LIVE cloud site:
REM        https://5-223-53-58.sslip.io/
REM
REM  It pushes this folder to the Ohjjam repo; the server auto-pulls in ~2 min
REM  and restarts, so the live site catches up on its own.
REM
REM  ASCII-only on purpose (the cp949 console garbles non-ASCII text).
REM
REM  KEY FIX vs the old version: it now SYNCS with the remote first
REM  (fetch + rebase). When another PC (or the survivors work) has pushed new
REM  commits, git used to reject the push with "fetch first" and nothing got
REM  deployed. This version pulls those commits down, replays your change on
REM  top, then pushes -- so the deploy no longer silently fails.
REM ==========================================================================
setlocal
cd /d "%~dp0"

echo.
echo === Bubble Simulator deploy  to  https://5-223-53-58.sslip.io/ ===
echo.

REM --- 1) stage + commit local changes (skip the commit if nothing changed) ---
git add -A
git diff --cached --quiet
if errorlevel 1 (
  git commit -m "deploy update"
) else (
  echo No new local changes -- will still sync/push in case a prior push failed.
)

REM --- 2) sync with the remote so the push can fast-forward ---
echo.
echo Syncing with remote (fetch + rebase)...
git fetch ohjam main
if errorlevel 1 (
  echo.
  echo ERROR: could not fetch from ohjam. Check internet/VPN and run this again.
  goto :end
)
git rebase ohjam/main
if errorlevel 1 (
  echo.
  echo ======================================================================
  echo  REBASE CONFLICT: local and remote edited the SAME lines.
  echo  Nothing was pushed. Rolling the rebase back so your files stay intact.
  echo  Ask Claude to resolve the conflict, then run this again.
  echo ======================================================================
  git rebase --abort
  goto :end
)

REM --- 3) push (saved git cred is read-only, so borrow the logged-in gh CLI) ---
echo.
echo Pushing to ohjam/main...
git -c credential.helper= -c "credential.helper=!gh auth git-credential" push ohjam main
if errorlevel 1 (
  echo.
  echo ERROR: push failed. Is gh logged in?  Try:  gh auth login
  goto :end
)

echo.
echo ======================================================================
echo  Done. The live server pulls the latest within about 2 minutes:
echo        https://5-223-53-58.sslip.io/
echo ======================================================================

:end
echo.
pause
endlocal
