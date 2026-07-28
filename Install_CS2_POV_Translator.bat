@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Install CS2 POV Translator v0.9.8

rem ASCII-only installer stub.
rem Keep all Chinese UI text inside Python/docs to avoid Windows CMD GBK/UTF-8 parse errors.
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"

echo ===============================================================
echo CS2 POV Translator v0.9.8 Installer
echo ===============================================================
echo Current install directory: %CD%
echo.
echo This will prepare a local Python environment for this folder.
echo Do not extract the new zip over an old cs2pov_arch_project folder.
echo Recommended clean-room folder: cs2pov_arch_project_v0_9_8
echo.
echo Python auto-discovery supports:
echo   python, py -3, python3, common Anaconda/Miniconda paths.
echo.
echo After installation, double-click START_HERE_DOUBLE_CLICK.bat.
echo.

if exist "%CD%\cs2pov_arch_project\Start_CS2_POV_Translator.bat" (
  echo [WARNING] Nested cs2pov_arch_project folder detected.
  echo [WARNING] You may have extracted the new zip inside an old project folder.
  echo [WARNING] Please close this window and extract to a clean-room folder.
  echo.
)

pause

echo [1/5] Finding Python 3.11+...
call :find_python
if not defined CS2POV_PY (
  echo.
  echo [ERROR] Python 3.11+ was not found.
  echo.
  echo Tried:
  echo   python
  echo   py -3
  echo   python3
  echo   USERPROFILE\anaconda3\python.exe
  echo   USERPROFILE\miniconda3\python.exe
  echo   ProgramData\Anaconda3\python.exe
  echo   ProgramData\Miniconda3\python.exe
  echo   common Python311/Python312/Python313 install paths
  echo.
  echo If you use Anaconda, open Anaconda Prompt and run:
  echo   cd /d "%CD%"
  echo   python -m venv .venv
  echo   .venv\Scripts\python.exe -m pip install -e ".[all]"
  echo.
  pause
  exit /b 1
)
echo Found Python command: %CS2POV_PY%
%CS2POV_PY% --version

echo.
echo [2/5] Creating virtual environment .venv...
if not exist ".venv\Scripts\python.exe" (
  %CS2POV_PY% -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Failed to create .venv.
    pause
    exit /b 1
  )
) else (
  echo .venv already exists. Reusing it.
)

echo.
echo [3/5] Installing dependencies. This can take a while...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
  echo [WARN] pip upgrade failed. Continuing with current pip.
)
".venv\Scripts\python.exe" -m pip install -e ".[all]"
if errorlevel 1 (
  echo.
  echo [ERROR] Dependency installation failed. Please check network/proxy and retry.
  pause
  exit /b 1
)

echo.
echo [4/5] Running launch sanity check...
".venv\Scripts\python.exe" -X utf8 scripts\launch_sanity_check.py
if errorlevel 2 (
  echo.
  echo [ERROR] Launch sanity check failed.
  echo Please extract to a clean-room folder and reinstall.
  pause
  exit /b 2
)

echo.
echo [5/5] Running setup-check...
".venv\Scripts\python.exe" -X utf8 -m cs2pov setup-check

echo.
echo Installation completed. You can now double-click START_HERE_DOUBLE_CLICK.bat.
echo.
pause
exit /b 0

:find_python
call :try_python_cmd python
call :try_python_cmd py -3
call :try_python_cmd python3
call :try_python_path "%USERPROFILE%\anaconda3\python.exe"
call :try_python_path "%USERPROFILE%\miniconda3\python.exe"
call :try_python_path "%LOCALAPPDATA%\anaconda3\python.exe"
call :try_python_path "%LOCALAPPDATA%\miniconda3\python.exe"
call :try_python_path "%ProgramData%\Anaconda3\python.exe"
call :try_python_path "%ProgramData%\Miniconda3\python.exe"
call :try_python_path "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
call :try_python_path "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
call :try_python_path "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
call :try_python_path "%ProgramFiles%\Python313\python.exe"
call :try_python_path "%ProgramFiles%\Python312\python.exe"
call :try_python_path "%ProgramFiles%\Python311\python.exe"
goto :eof

:try_python_cmd
if defined CS2POV_PY goto :eof
%* -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 set "CS2POV_PY=%*"
goto :eof

:try_python_path
if defined CS2POV_PY goto :eof
if exist "%~1" (
  "%~1" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
  if not errorlevel 1 set "CS2POV_PY="%~1""
)
goto :eof
