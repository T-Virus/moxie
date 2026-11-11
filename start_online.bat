@echo off
setlocal
cd /d "%~dp0"

echo ================================================================
echo   Moxie Online - One-Click Start
echo   Backend Docker (8000) + Client (5190) + Admin (5180)
echo ================================================================
echo.

REM ---------- dependency checks ----------
docker info >nul 2>nul
if errorlevel 1 (
  echo [x] Docker is not running or not installed. Start Docker Desktop first.
  pause
  exit /b 1
)

where node >nul 2>nul
if errorlevel 1 (
  echo [x] Node.js is not installed or not in PATH.
  pause
  exit /b 1
)

REM ---------- 0. ensure server/.env exists (docker compose fails hard if missing) ----------
REM NOTE: cmd "if exist" mis-detects dot-files (.env / .env.example) on some Windows,
REM so we use "dir" to test existence and check "copy" errorlevel instead.
dir "server\.env" >nul 2>nul
if errorlevel 1 (
  copy /Y "server\.env.example" "server\.env" >nul 2>nul
  if errorlevel 1 (
    echo [x] server\.env.example not found - cannot create server\.env. Backend will not start.
    pause
    exit /b 1
  ) else (
    echo [!] server\.env was missing - copied from server\.env.example.
    echo      EDIT server\.env before re-running: set JWT_SECRET to at least 32 chars,
    echo      LICENSE_PRIVATE_KEY_PEM, CORS_ALLOW_ORIGINS, DB and MinIO passwords.
    echo      Or run:  bash scripts/deploy/preflight.sh --gen-secrets
  )
)

REM ---------- 1. backend Docker ----------
echo [1/3] Starting backend Docker (Postgres / Redis / MinIO / api / worker / scheduler)...
pushd server
docker compose up -d --build
if errorlevel 1 (
  echo [x] Backend Docker failed to start. Check server\docker-compose.yml and server\.env
  popd
  pause
  exit /b 1
)
popd

REM ---------- 2. client ----------
echo [2/3] Starting client (http://127.0.0.1:5190)...
if not exist "client\node_modules" (
  echo     First run: installing client dependencies, may take a few minutes...
  pushd client
  call npm install
  if errorlevel 1 (
    echo [x] Client dependency install failed.
    popd
    pause
    exit /b 1
  )
  popd
)
start "Moxie Client 5190" /d "%~dp0client" cmd /k npm run dev

REM ---------- 3. admin ----------
echo [3/3] Starting admin (http://127.0.0.1:5180)...
if not exist "admin\node_modules" (
  echo     First run: installing admin dependencies, may take a few minutes...
  pushd admin
  call npm install
  if errorlevel 1 (
    echo [x] Admin dependency install failed.
    popd
    pause
    exit /b 1
  )
  popd
)
start "Moxie Admin 5180" /d "%~dp0admin" cmd /k npm run dev

echo.
echo ================================================================
echo   Waiting for backend API http://127.0.0.1:8000/healthz (first run builds image + migrates DB, may take minutes)...
echo ================================================================
set "API_OK=0"
for /L %%i in (1,1,90) do (
  curl.exe -s -o NUL --max-time 3 http://127.0.0.1:8000/healthz >nul 2>nul
  if not errorlevel 1 (
    set "API_OK=1"
    goto api_ready
  )
  ping -n 2 127.0.0.1 >nul
)
:api_ready
if "%API_OK%"=="1" (
  echo   [OK] Backend API ready: http://127.0.0.1:8000   docs at http://127.0.0.1:8000/docs
) else (
  echo   [!] Backend API not ready within wait window. Diagnose with:
  echo        cd server ^&^& docker compose ps
  echo        cd server ^&^& docker compose logs --tail=80 api
)
echo.
echo ================================================================
echo   Started.
echo     Backend API : http://127.0.0.1:8000  (healthz, docs)
echo     Client      : http://localhost:5190
echo     Admin       : http://localhost:5180
echo     Stop        : run stop_online.bat
echo ================================================================
echo.

if "%API_OK%"=="1" start "" http://127.0.0.1:8000/docs
start "" http://localhost:5190/
start "" http://localhost:5180/

echo.
echo Client and Admin are running in their own windows.
echo Press any key to close THIS window (services keep running).
pause >nul

endlocal
