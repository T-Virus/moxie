@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ================================================================
echo   Moxie - Stop ALL (server + web + admin + offline)
echo ================================================================
echo.

echo [1/4] Stopping processes recorded in logs\*.pid ...
for %%f in ("%~dp0logs\*.pid") do call :kill_pid_file "%%~ff"
del /q "%~dp0logs\*.pid" >nul 2>nul

echo [2/4] Stopping dev servers by command line...
call :stop_proc node.exe "client\node_modules"
call :stop_proc node.exe "admin\node_modules"
call :stop_proc python.exe "webapp.py"

echo       Closing Android web preview windows...
call :stop_proc msedge.exe "MoxieMobilePreview"
call :stop_proc chrome.exe "MoxieMobilePreview"

echo [3/4] Freeing ports 8765 / 5190 / 5180 ...
call :kill_port 8765
call :kill_port 5190
call :kill_port 5180

echo [4/4] Stopping server (Docker)...
docker info >nul 2>nul
if errorlevel 1 (
  echo       Docker not running - skipped.
  goto done
)
pushd server
docker compose down
popd

:done
echo.
echo ================================================================
echo   All services stopped.
echo.
echo   Data volumes are kept. To wipe them as well, run:
echo     cd server ^&^& docker compose down -v
echo ================================================================
echo.
pause
exit /b 0

REM %1 = pid file path
:kill_pid_file
set "PIDVAL="
for /f "usebackq delims=" %%v in ("%~1") do set "PIDVAL=%%v"
if not defined PIDVAL goto :eof
taskkill /PID %PIDVAL% /T /F >nul 2>nul
echo       killed recorded pid %PIDVAL%
goto :eof

REM %1 = image name, %2 = command-line fragment
:stop_proc
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq '%1' -and $_.CommandLine -like '*%2*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host ('      stopped ' + $_.Name + ' pid ' + $_.ProcessId) }"
goto :eof

REM %1 = port. Kill whatever is listening on it.
:kill_port
set "FOUND=0"
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%1 " ^| findstr "LISTENING"') do (
  set "FOUND=1"
  taskkill /PID %%p /T /F >nul 2>nul
  echo       killed pid %%p on port %1
)
if "%FOUND%"=="0" echo       nothing on port %1
goto :eof
