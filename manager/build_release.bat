@echo off
setlocal
title RobotsSystem Release Builder
py -3.10 "%~dp0deploy.py" package --offline %*
set EXIT_CODE=%ERRORLEVEL%
echo.
pause
exit /b %EXIT_CODE%
