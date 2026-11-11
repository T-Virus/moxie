@echo off
rem ============================================================
rem One-command full build for Windows + Android clients.
rem Steps: web build (auto-skipped when fresh) -> PyInstaller exe
rem        and/or Android APK (Gradle + Chaquopy) -> artifact check.
rem Real logic: src\build_app.py / mobile\build_apk.py
rem
rem Usage:
rem   build_exe.bat                  Windows exe + Android APK (default)
rem   build_exe.bat --target win     Windows exe only
rem   build_exe.bat --target android Android APK only
rem
rem Options: --skip-web (Python-only changes) / --force-web
rem          --android-rebuild (reuse installed Android toolchain)
rem          --packager auto|nuitka|pyinstaller (default auto: Nuitka, fallback PyInstaller)
rem Requires: Node.js (npm) + pip install nuitka pywebview pycryptodome
rem           pillow openai
rem           + VS Build Tools "Desktop development with C++" workload (provides MSVC and Windows SDK)
rem Output:   dist\*.exe  +  mobile\dist\*.apk
rem ============================================================
cd /d "%~dp0"
python src\build_app.py %*
echo.
pause
