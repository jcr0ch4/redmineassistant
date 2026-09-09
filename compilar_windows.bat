@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

rem ================================================================
rem  compilar_windows.bat - build RedmineAssitant.exe (Windows)
rem
rem  Usage:
rem     compilar_windows.bat                 (Flet default icon)
rem     compilar_windows.bat logo.ico        (custom icon)
rem     compilar_windows.bat logo.ico debug  (console build for logs)
rem
rem  Requires: Python 3.10-3.12 x64 (via PATH or "py" launcher).
rem  Output: dist\RedmineAssitant.exe (one-file, no console).
rem
rem  The Flet desktop client ships in "flet-runtime\flet-windows.zip"
rem  and is seeded into the local cache on first run - no GitHub
rem  download needed (avoids SSL/CERTIFICATE_VERIFY_FAILED caused by
rem  corporate proxies that intercept HTTPS).
rem ================================================================

set "PY_CMD=py"
set "ICON="
set "EXTRA="

rem --- detect Python (prefer 3.12) ---
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 (
  set "PY_CMD=py -3.12"
  goto :python_ok
)
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
  set "PY_CMD=py -3"
  goto :python_ok
)
python -c "import sys" >nul 2>&1
if not errorlevel 1 (
  set "PY_CMD=python"
  goto :python_ok
)
echo [ERROR] Python not found. Install Python 3.10-3.12 x64 and tick "Add to PATH".
pause
exit /b 1

:python_ok
echo [0/5] Python: %PY_CMD%
for /f "delims=" %%v in ('%PY_CMD% -c "import sys;print(^'%%d.%%d^'%%sys.version_info[:2])"') do set "PYVER=%%v"
echo         version = %PYVER%
%PY_CMD% -c "import sys;sys.exit(0 if sys.version_info < (3,13) else 1)" >nul 2>&1
if errorlevel 1 (
  echo         [WARN] Python 3.13+ detected. Flet 0.86.5 / PyInstaller 6.22.2
  echo                are tested with 3.10-3.12. Install Python 3.12 if the
  echo                build fails on 3.14.
)

if not "%~1"=="" set "ICON=-i %~1"
if /i "%~2"=="debug" set "EXTRA=-D"

rem --- seed Flet client cache (avoids GitHub download w/ SSL errors) ---
if not exist "%USERPROFILE%\.flet\client\flet-desktop-full-0.86.5" (
  if exist "flet-runtime\flet-windows.zip" (
    echo [1/5] Seeding Flet client cache from bundled archive ...
    powershell -NoProfile -Command "$d=[IO.Path]::Combine($env:USERPROFILE,'.flet','client','flet-desktop-full-0.86.5');New-Item -ItemType Directory -Force -Path $d|Out-Null;Expand-Archive -Path '%~dp0flet-runtime\flet-windows.zip' -DestinationPath $d -Force"
    if errorlevel 1 goto :erro
  ) else (
    echo [1/5] flet-runtime missing - flet will try to download the client.
  )
) else (
  echo [1/5] Flet client cache already present.
)

echo [2/5] Virtualenv (.venv) ...
if not exist ".venv\Scripts\python.exe" (
  %PY_CMD% -m venv .venv
  if errorlevel 1 goto :erro
)
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
if errorlevel 1 goto :erro

echo [3/5] Installing dependencies ...
".venv\Scripts\pip.exe" install -r requirements.txt
if errorlevel 1 goto :erro
".venv\Scripts\pip.exe" install -r requirements-dev.txt
if errorlevel 1 goto :erro

echo [4/5] Syntax sanity check (py_compile) ...
".venv\Scripts\python.exe" -m py_compile app_flet.py ollama_client.py config_manager.py ferramentas.py redmine_api.py assistente_db.py paths.py
if errorlevel 1 goto :erro

echo [5/5] Building executable with flet pack ...
".venv\Scripts\flet.exe" pack app_flet.py -n RedmineAssitant %ICON% %EXTRA% -y
if errorlevel 1 goto :erro

echo.
echo ================================================================
echo  DONE: dist\RedmineAssitant.exe
echo.
echo  Test: copy the exe to a clean folder and run it.
echo  On first run the app creates config.json and assistente_local.db
echo  next to the executable (data never bundled into the exe).
echo ================================================================
pause
exit /b 0

:erro
echo.
echo [ERROR] Build stopped. Review the messages above.
pause
exit /b 1
