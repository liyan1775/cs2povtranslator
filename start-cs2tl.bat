@echo off
chcp 65001 >nul
cd /d %~dp0

echo ========================================
echo   CS2 POV Translator
echo   CS2 Faceit demo voice -^> Chinese SRT
echo ========================================
echo.

.venv\Scripts\cs2tl.exe wizard
pause
