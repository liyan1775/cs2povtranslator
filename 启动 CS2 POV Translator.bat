@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title CS2 POV Translator

echo ===============================================================
echo CS2 POV Translator v0.8.5
echo Release-ready local-first bilingual subtitle toolkit
echo ===============================================================
echo.
echo This launcher opens an interactive menu with guided explanations.
echo New users: choose [2] setup-check first, then [1] create a job.
echo Existing jobs: use inspect, explain-output, export, retranslate,
echo resume, glossary, or feedback from the menu.
echo.

if exist ".venv\Scripts\python.exe" (
  set "CS2POV_PY=.venv\Scripts\python.exe"
) else (
  echo [ERROR] Local virtual environment was not found: .venv\Scripts\python.exe
  echo.
  echo Recommended: double-click Install_CS2_POV_Translator.bat in this folder.
  echo.
  echo Manual PowerShell steps:
  echo   python -m venv .venv
  echo   .\.venv\Scripts\Activate.ps1
  echo   pip install -e ".[all]"
  echo   cs2pov setup-check
  echo.
  echo After installation succeeds, double-click this launcher again.
  echo.
  pause
  exit /b 1
)

"%CS2POV_PY%" -X utf8 -m cs2pov.cli.launcher
if errorlevel 1 (
  echo.
  echo The program exited with an error. If you already have a job,
  echo choose the feedback option from the menu next time, or run:
  echo   cs2pov feedback output
)
echo.
pause
