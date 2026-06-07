@echo off
chcp 65001 >nul
cd /d %~dp0

echo ========================================
echo   CS2 POV Translator v0.1
echo   CS2 Faceit demo voice -^> Chinese SRT
echo ========================================
echo.

echo Starting server...
.venv\Scripts\python.exe launch-cs2tl.py
pause
