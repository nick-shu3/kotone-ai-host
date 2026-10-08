@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
".venv\Scripts\python.exe" -I -B check_windows.py
if errorlevel 1 goto fail
echo Offline Windows checks passed. Rights and publication decisions remain separate.
pause
exit /b 0
:missing
echo Run setup.bat first.
:fail
echo Windows checks incomplete or failed. Do not claim Windows verification yet.
pause
exit /b 1
