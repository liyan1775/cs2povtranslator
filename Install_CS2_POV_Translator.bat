@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Install CS2 POV Translator

echo ===============================================================
echo CS2 POV Translator v0.8.5 installer
echo ===============================================================
echo This script prepares the local Python environment for this folder.
echo It may take several minutes because dependencies are downloaded.
echo.
echo Steps:
echo   [1/4] Check Python
echo   [2/4] Create .venv
echo   [3/4] Install dependencies: pip install -e ".[all]"
echo   [4/4] Run setup-check
echo.
pause

echo [1/4] Checking Python...
python --version
if errorlevel 1 (
  echo.
  echo [ERROR] Python was not found. Please install Python 3.11+ and enable PATH.
  pause
  exit /b 1
)

echo.
echo [2/4] Creating virtual environment .venv...
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Failed to create .venv.
    pause
    exit /b 1
  )
) else (
  echo .venv already exists. Reusing it.
)

echo.
echo [3/4] Installing dependencies. This can take a while...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
  echo [WARN] pip upgrade failed. Continuing with current pip.
)
".venv\Scripts\python.exe" -m pip install -e ".[all]"
if errorlevel 1 (
  echo.
  echo [ERROR] Dependency installation failed.
  echo Please check network/proxy and try again.
  pause
  exit /b 1
)

echo.
echo [4/4] Running setup-check...
".venv\Scripts\python.exe" -X utf8 -m cs2pov setup-check

echo.
echo Installation script finished.
echo If setup-check says ready or partial-ready, double-click Start_CS2_POV_Translator.bat.
echo.
pause
