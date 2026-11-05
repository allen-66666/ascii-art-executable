@echo off
chcp 65001 >nul
cd /d "%~dp0"
python scripts\selfcheck.py
echo.
pause
