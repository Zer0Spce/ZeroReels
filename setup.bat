@echo off
setlocal
cd /d "%~dp0"
echo.
echo ========================================
echo   ZeroReels v0.3 - First Time Setup
echo ========================================
echo.
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher not found. Install Python 3.11 or newer first.
  pause
  exit /b 1
)
if not exist .venv (
  echo Creating virtual environment...
  py -3 -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -e .
if errorlevel 1 (
  echo.
  echo Setup failed. See the error above.
  pause
  exit /b 1
)
echo.
echo Setup complete. Run run.bat to start ZeroReels.
pause
