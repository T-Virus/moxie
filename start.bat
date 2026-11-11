@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist "logs" mkdir "logs"
set "LOGS=%~dp0logs"

echo ================================================================
echo   Moxie - Start ALL
echo     Server (Docker) : http://127.0.0.1:8000
echo     Web client      : http://localhost:5190
echo     Admin console   : http://localhost:5180
echo     Offline client  : http://localhost:8765
echo     Android UI      : http://localhost:8765/?mobile=1 (phone window)
echo ================================================================
echo.

REM ---------- capability checks ----------
set "HAS_DOCKER=1"
set "HAS_PY=1"
set "HAS_NODE=1"

docker info >nul 2>nul
if errorlevel 1 set "HAS_DOCKER=0"
where python >nul 2>nul
if errorlevel 1 set "HAS_PY=0"
where node >nul 2>nul
if errorlevel 1 set "HAS_NODE=0"

if "%HAS_PY%"=="0" echo [warn] python not found - offline client will be skipped.
if "%HAS_DOCKER%"=="0" echo [warn] Docker not running - server will be skipped.
if "%HAS_NODE%"=="0" echo [warn] Node.js not found - web client / admin will be skipped.
echo.

REM ---------- 0. ensure server/.env exists (docker compose fails hard if missing) ----------
if "%HAS_DOCKER%"=="1" (
  dir "server\.env" >nul 2>nul
  if errorlevel 1 (
    copy /Y "server\.env.example" "server\.env" >nul 2>nul
    if errorlevel 1 (
      echo [x] server\.env.example not found - cannot create server\.env. Backend will not start.
    ) else (
      echo [!] server\.env was missing - copied from server\.env.example. Edit it before re-running.
    )
  )
)

REM ---------- 1. server (docker) ----------
echo [1/5] Server (Postgres/Redis/MinIO/api/worker/scheduler)...
if "%HAS_DOCKER%"=="0" goto web
pushd server
docker compose up -d
if errorlevel 1 (
  echo [x] Server failed to start. See: server\docker-compose.yml and server\.env
  popd
  goto web
)
popd
echo       waiting for http://127.0.0.1:8000/healthz ...
powershell -NoProfile -Command "$ok=$false; for($i=0;$i -lt 60;$i++){ try{ $r=Invoke-WebRequest -Uri 'http://127.0.0.1:8000/healthz' -UseBasicParsing -TimeoutSec 3; if($r.StatusCode -eq 200){$ok=$true;break} }catch{}; Start-Sleep -Seconds 2 }; if($ok){Write-Host '      server ready'}else{Write-Host '      server not ready - check: cd server ^&^& docker compose logs api'}"

:web
REM ---------- 2. web client (5190) ----------
echo [2/5] Web client...
if "%HAS_NODE%"=="0" goto admin
if not exist "client\node_modules" (
  echo       first run: running npm install, this may take a few minutes...
  pushd client
  call npm install
  popd
)
call :stop_proc node.exe "client\node_modules"
call :run_hidden web 5190 "npm run dev" "%~dp0client"

:admin
REM ---------- 3. admin console (5180) ----------
echo [3/5] Admin console...
if "%HAS_NODE%"=="0" goto offline
if not exist "admin\node_modules" (
  echo       first run: running npm install, this may take a few minutes...
  pushd admin
  call npm install
  popd
)
call :stop_proc node.exe "admin\node_modules"
call :run_hidden admin 5180 "npm run dev" "%~dp0admin"

:offline
REM ---------- 4. offline client (8765) ----------
echo [4/5] Offline client...
if "%HAS_PY%"=="0" goto android
set "PYEXE="
for /f "delims=" %%i in ('where python 2^>nul') do if not defined PYEXE set "PYEXE=%%i"
if not defined PYEXE (
  echo       [warn] python.exe not resolved - skipped.
  goto android
)
set OFFCMD="%PYEXE%" src\webapp.py
call :stop_proc python.exe "webapp.py"
call :run_hidden offline 8765 "%OFFCMD%" "%~dp0"

:android
REM ---------- 5. android UI (mobile web preview) ----------
echo [5/5] Android UI (mobile web preview)...
call :android_start
goto done

:done
echo.
echo ================================================================
echo   Started. Logs are in: logs\ (web.log / admin.log / offline.log)
echo.
echo     Server (Docker) : http://127.0.0.1:8000  (/healthz)
echo     Web client      : http://localhost:5190
echo     Admin console   : http://localhost:5180
echo     Offline client  : http://localhost:8765
echo     Android UI      : http://localhost:8765/?mobile=1
echo.
echo   Stop everything : run stop_all.bat
echo ================================================================
echo.

ping -n 3 127.0.0.1 >nul

if "%HAS_NODE%"=="1" start "" http://localhost:5190/
if "%HAS_NODE%"=="1" start "" http://localhost:5180/
if "%HAS_PY%"=="1" start "" http://localhost:8765/

echo Press any key to close THIS window (services keep running).
pause >nul
exit /b 0

REM ================= helpers =================

REM %1=name %2=port %3=command line %4=workdir
:run_hidden
call :stop_port %2
call :wait_port_free %2
if errorlevel 1 (
  echo       [x] port %2 is still busy - skipped. Run stop_all.bat then retry.
  goto :eof
)
powershell -NoProfile -Command "$p = Start-Process -FilePath $env:ComSpec -ArgumentList '/c','%~3' -WorkingDirectory '%~4.' -RedirectStandardOutput '%LOGS%\%~1.out.log' -RedirectStandardError '%LOGS%\%~1.err.log' -WindowStyle Hidden -PassThru; Set-Content -Path '%LOGS%\%~1.pid' -Value $p.Id -Encoding ascii"
call :wait_http %2
if errorlevel 1 (
  echo       [x] port %2 did not come up. Last lines of %~1.err.log:
  powershell -NoProfile -Command "Get-Content '%LOGS%\%~1.err.log' -Tail 8 -ErrorAction SilentlyContinue"
) else (
  echo       ready on port %2.
)
goto :eof

REM %1 = image name (node.exe / python.exe), %2 = command-line fragment
:stop_proc
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq '%1' -and $_.CommandLine -like '*%2*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host ('      stopped ' + $_.Name + ' pid ' + $_.ProcessId) }"
goto :eof

REM %1 = port. Kill whatever is listening on it.
:stop_port
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%1 " ^| findstr "LISTENING"') do (
  taskkill /PID %%p /T /F >nul 2>nul
  echo       killed pid %%p holding port %1
)
goto :eof

REM %1 = port. Wait until nothing listens on it (max ~15s).
:wait_port_free
set /a FREEWAIT=0
:free_loop
netstat -ano | findstr ":%1 " | findstr "LISTENING" >nul 2>nul
if errorlevel 1 exit /b 0
set /a FREEWAIT+=1
if %FREEWAIT% GEQ 15 exit /b 1
ping -n 2 127.0.0.1 >nul
goto free_loop

REM %1 = port. Wait until HTTP answers (max ~40s).
:wait_http
set /a WAITED=0
:wait_http_loop
curl.exe -s -o NUL --max-time 2 http://localhost:%1/ >nul 2>nul
if not errorlevel 1 exit /b 0
set /a WAITED+=1
if %WAITED% GEQ 20 exit /b 1
ping -n 2 127.0.0.1 >nul
goto wait_http_loop

:android_start
set "BUSY_WAIT=0"
:android_wait
curl.exe -s -o NUL --max-time 2 "http://localhost:8765/?mobile=1" >nul 2>nul
if not errorlevel 1 goto android_open
set /a BUSY_WAIT+=1
if %BUSY_WAIT% GEQ 10 goto android_adb
ping -n 2 127.0.0.1 >nul
goto android_wait

:android_open
set "BROWSER="
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "BROWSER=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not defined BROWSER if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "BROWSER=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if not defined BROWSER if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "BROWSER=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined BROWSER if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "BROWSER=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined BROWSER (
  echo       no Edge/Chrome found - open manually: http://localhost:8765/?mobile=1
  goto android_adb
)
set "PROFILE=%LOCALAPPDATA%\MoxieMobilePreview"
powershell -NoProfile -Command "$a=@('--new-window','http://localhost:8765/?mobile=1','--window-size=430,932','--user-data-dir=%PROFILE%','--no-first-run','--no-default-browser-check'); $p=Start-Process -FilePath '%BROWSER%' -ArgumentList $a -PassThru; Set-Content -Path '%LOGS%\android.pid' -Value $p.Id -Encoding ascii"
echo       opened phone-sized window: http://localhost:8765/?mobile=1

:android_adb
set "ADB="
where adb >nul 2>nul && set "ADB=adb"
if not defined ADB if exist "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" set "ADB=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"
if not defined ADB (
  echo       adb not found - real device install skipped (web preview above is enough).
  goto :eof
)
set "DEVICES="
"%ADB%" devices > "%TEMP%\moxie_adb.txt" 2>nul
for /f "skip=1 tokens=1,2" %%a in ('type "%TEMP%\moxie_adb.txt"') do if "%%b"=="device" set "DEVICES=1"
if not defined DEVICES (
  echo       no device/emulator connected - real device install skipped.
  goto :eof
)
set "APK="
for %%f in ("%~dp0mobile\dist\*.apk") do set "APK=%%~ff"
if not defined APK (
  echo       no APK found in mobile\dist - build it with: python mobile\build_apk.py
  goto :eof
)
echo       installing %APK% to the connected device...
"%ADB%" install -r "%APK%" >nul 2>nul
if errorlevel 1 (
  echo       [x] install failed - check the device screen for confirmation.
  goto :eof
)
"%ADB%" shell monkey -p com.mobit.writer -c android.intent.category.LAUNCHER 1 >nul 2>nul
echo       android app launched on the device.
goto :eof
