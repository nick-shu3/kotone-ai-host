@echo off
cd /d "%~dp0"
echo Preparing an isolated Python environment in this folder.
echo Downloads hashed Pillow from PyPI and pinned FFmpeg 9.0.2 from gyan.dev. No administrator rights needed.
if exist ".venv\Scripts\python.exe" goto install
py -3 --version >nul 2>&1
if errorlevel 1 goto fallback
py -3 -I -m venv .venv
if errorlevel 1 goto fail
goto install
:fallback
python -I -m venv .venv
if errorlevel 1 goto fail
:install
".venv\Scripts\python.exe" -I -m pip --isolated install --disable-pip-version-check --require-hashes --only-binary=:all: --index-url https://pypi.org/simple -r requirements.txt
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -I install_ffmpeg.py
if errorlevel 1 goto fail
echo Setup complete. Run start.bat next.
pause
exit /b 0
:fail
echo Setup failed. Use 64-bit Python 3.10 to 3.14 and check your internet connection.
echo Please share the error message, not any API key.
pause
exit /b 1
