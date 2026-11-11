@echo off
rem ============================================================================
rem package.bat - Windows one-click packaging (calls scripts/package.sh)
rem
rem Prefer the bash bundled with Git for Windows; if not found, tell user to run in Git Bash.
rem Output: build\moxie-deploy-<timestamp>.tar.gz
rem ============================================================================
setlocal EnableExtensions
cd /d "%~dp0"

set "BASH="
for %%p in (
  "%ProgramFiles%\Git\bin\bash.exe"
  "%ProgramFiles(x86)%\Git\bin\bash.exe"
  "%LOCALAPPDATA%\Programs\Git\bin\bash.exe"
) do (
  if exist "%%~p" set "BASH=%%~p"
)
if not defined BASH (
  where bash >nul 2>nul && set "BASH=bash"
)

if not defined BASH (
  echo [x] Git Bash / bash not found.
  echo     Install Git for Windows, then run in its Git Bash:
  echo         bash scripts/package.sh
  pause
  exit /b 1
)

echo [package] Running scripts/package.sh %* with %BASH%
"%BASH%" scripts/package.sh %*
endlocal
