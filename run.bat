@echo off
setlocal EnableExtensions
title Amazon UK Opportunity Finder
cd /d "%~dp0"

echo.
echo   Amazon UK Opportunity Finder
echo   ============================
echo.

rem --- 1. Virtual environment ------------------------------------------------
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
  if errorlevel 1 (
    echo   [1/4] The existing .venv is broken or too old - recreating it ...
    rmdir /s /q ".venv"
  ) else (
    echo   [1/4] Virtual environment found.
    goto install
  )
)

set "PY="
for %%V in (3.12 3.11 3.13 3.14) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo   [!] Python 3.11 or newer was not found.
  echo       Install it from https://www.python.org/downloads/
  echo       and tick "Add python.exe to PATH" during setup, then run this file again.
  echo.
  pause
  exit /b 1
)
echo   [1/4] Creating the virtual environment with %PY% ...
%PY% -m venv .venv
if errorlevel 1 (
  echo   [!] Could not create the virtual environment.
  pause
  exit /b 1
)

:install
rem --- 2. Requirements ------------------------------------------------------------
echo   [2/4] Installing / checking requirements ...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
  echo   [!] Installing requirements failed. Check your internet connection and try again.
  pause
  exit /b 1
)

rem --- 3. Database -----------------------------------------------------------------
echo   [3/4] Preparing the data folder and database ...
".venv\Scripts\python.exe" app.py --init-only
if errorlevel 1 (
  echo   [!] The database could not be prepared. See data\logs\app.log for details.
  pause
  exit /b 1
)

rem --- 4. Start ----------------------------------------------------------------------
echo   [4/4] Starting the app at http://127.0.0.1:8877  (set AOF_PORT in .env to change it)
echo.
".venv\Scripts\python.exe" app.py
echo.
echo   The app has stopped.
pause
