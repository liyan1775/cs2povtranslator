@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title CS2 POV Translator v0.9.8

rem ASCII-only launcher stub.
rem Keep all Chinese UI text inside Python to avoid Windows CMD GBK/UTF-8 parse errors.
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"

echo ===============================================================
echo CS2 POV Translator v0.9.8
echo Main feature: Comms Overlay assets for CapCut/Jianying
echo ===============================================================
echo Current directory: %CD%
echo.
echo This .bat file is ASCII-only by design.
echo Chinese menu text will be printed by the Python launcher after startup check.
echo.

if exist "%CD%\cs2pov_arch_project\Start_CS2_POV_Translator.bat" (
  echo [WARNING] Nested cs2pov_arch_project folder detected.
  echo [WARNING] You may have extracted the new zip inside an old project folder.
  echo [WARNING] Please use a clean-room folder, for example cs2pov_arch_project_v0_9_8.
  echo.
)

if not exist ".venv\Scripts\python.exe" (
  echo [INFO] Local virtual environment not found.
  echo [INFO] Starting installer first. This may take a while.
  echo.
  call Install_CS2_POV_Translator.bat
  if errorlevel 1 (
    echo.
    echo [ERROR] Installer failed. Please read the messages above.
    echo.
    pause
    exit /b 1
  )
)

if exist ".venv\Scripts\python.exe" (
  set "CS2POV_PY=.venv\Scripts\python.exe"
) else (
  echo [ERROR] Local virtual environment still not found after installer.
  echo Please run Install_CS2_POV_Translator.bat from this folder.
  echo.
  pause
  exit /b 1
)

"%CS2POV_PY%" -X utf8 scripts\launch_sanity_check.py
if errorlevel 2 (
  echo.
  echo [ERROR] Launch sanity check failed.
  echo Please extract this zip to a clean-room folder and reinstall.
  echo.
  pause
  exit /b 2
)

"%CS2POV_PY%" -X utf8 -m cs2pov.cli.launcher
if errorlevel 1 (
  echo.
  echo [ERROR] Program exited with an error.
  echo If an output job exists, open the menu next time and choose feedback,
  echo or run: cs2pov feedback output
)
echo.
pause
exit /b 0
