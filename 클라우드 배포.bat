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
REM  Only already tracked project files are deployed. Local videos, node_modules,
REM  browser traces, and generated analysis folders are intentionally excluded.
REM  The script also syncs with the remote before pushing.
REM ==========================================================================
setlocal
cd /d "%~dp0"

echo.
echo === Bubble Simulator deploy  to  https://5-223-53-58.sslip.io/ ===
echo.

REM --- 0) fail early with one useful message instead of many command errors ---
where git >nul 2>&1
if errorlevel 1 (
  echo ERROR: Git was not found. Install Git for Windows, then run this again.
  goto :end
)
where gh >nul 2>&1
if errorlevel 1 (
  echo ERROR: GitHub CLI ^(gh^) was not found. Install it, then run this again.
  goto :end
)
git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
  echo ERROR: this folder is not a Git repository.
  goto :end
)

REM --- 1) stage tracked changes only (never upload local/generated bulk files) ---
echo Staging tracked simulator files...
set "GIT_STAGE_LOG=%TEMP%\bubble-sim-git-stage-%RANDOM%.log"
git -c core.autocrlf=true add -u 2>"%GIT_STAGE_LOG%"
if errorlevel 1 (
  type "%GIT_STAGE_LOG%"
  del /q "%GIT_STAGE_LOG%" >nul 2>&1
  echo ERROR: staging tracked files failed.
  goto :end
)
del /q "%GIT_STAGE_LOG%" >nul 2>&1
git diff --cached --check
if errorlevel 1 (
  echo ERROR: staged files contain whitespace errors. Nothing was committed.
  goto :end
)
git diff --cached --quiet
if errorlevel 1 (
  git commit -m "Deploy current Bubble Simulator changes"
  if errorlevel 1 (
    echo ERROR: commit failed.
    goto :end
  )
) else (
  echo No tracked changes to commit. Local generated/untracked files are ignored.
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
  echo ERROR: push failed. Run "gh auth status" and, if needed, "gh auth login".
  goto :end
)

for /f %%H in ('git rev-parse --short HEAD') do set "DEPLOY_COMMIT=%%H"
echo.
echo ======================================================================
echo  Pushed commit %DEPLOY_COMMIT%. The live server updates within about 2 min:
echo        https://5-223-53-58.sslip.io/
echo ======================================================================

:end
echo.
pause
endlocal
