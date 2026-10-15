@echo off
cd /d "%~dp0"
where pwsh >nul 2>nul
if %errorlevel%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "scripts\stop.ps1"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\stop.ps1"
)
