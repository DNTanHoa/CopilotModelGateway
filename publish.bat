@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\publish-to-github.ps1"
set EXITCODE=%ERRORLEVEL%
echo.
if not "%EXITCODE%"=="0" echo Publish failed with exit code %EXITCODE%.
pause
exit /b %EXITCODE%
