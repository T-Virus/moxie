@echo off
setlocal
cd /d "%~dp0"

echo ================================================================
echo   Moxie Online - One-Click Stop
echo ================================================================
echo.

echo [1/2] Stopping backend Docker services...
pushd server
docker compose down
popd

echo [2/2] Closing client / admin windows...
taskkill /FI "WINDOWTITLE eq Moxie Client 5190*" /T /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq Moxie Admin 5180*" /T /F >nul 2>nul

echo.
echo Stopped. To also remove data volumes, run:
echo   cd server ^&^& docker compose down -v
echo.
pause
endlocal
