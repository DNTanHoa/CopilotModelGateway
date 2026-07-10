@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0gateway.ps1" %*
exit /b %ERRORLEVEL%
