@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Novel Workflow SelfTest

echo ============================================================
echo   Novel Serial Workflow - Self Test
echo   args:  --quick   also run a real short inference
echo          --no-net  skip network / Ollama checks
echo ============================================================
echo.
python src\selftest.py %*
echo.
pause
