@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto venv
py -3 --version >nul 2>&1
if errorlevel 1 goto fallback
py -3 -I server.py
goto done
:fallback
python --version >nul 2>&1
if errorlevel 1 goto missing
python -I server.py
goto done
:venv
".venv\Scripts\python.exe" -I server.py
goto done
:missing
echo Install Python 3.10 or newer from https://www.python.org/downloads/windows/
echo Enable "Add python.exe to PATH" if available, then try again.
:done
pause
