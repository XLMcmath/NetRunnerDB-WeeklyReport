@echo off
rem Double-click to fetch this week's NetrunnerDB decks right now.
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_weekly.ps1" -Force
echo.
echo Done. Opening the digest...
start "" "%~dp0index.html"
timeout /t 3 >nul
