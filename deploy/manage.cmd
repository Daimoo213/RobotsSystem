@echo off
setlocal
title RobotsSystem Deployment Manager
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0manage.ps1"
set EXIT_CODE=%ERRORLEVEL%
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%
