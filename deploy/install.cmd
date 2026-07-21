@echo off
setlocal
title RobotsSystem Installer
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
set EXIT_CODE=%ERRORLEVEL%
echo.
if not "%EXIT_CODE%"=="0" echo Installation failed. See deploy\install.log.
pause
exit /b %EXIT_CODE%
