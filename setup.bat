@echo off
setlocal
cd /d "%~dp0"
echo.
echo ========================================
echo   ZeroReels v0.4 - Windows Setup
echo ========================================
echo.
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher not found.
  echo Install Python 3.11, 3.12, or 3.13 from python.org, then run this again.
  pause
  exit /b 1
)
set "PYVER="
py -3.13 -c "import sys" >nul 2>nul && set "PYVER=-3.13"
if not defined PYVER py -3.12 -c "import sys" >nul 2>nul && set "PYVER=-3.12"
if not defined PYVER py -3.11 -c "import sys" >nul 2>nul && set "PYVER=-3.11"
if not defined PYVER (
  echo ZeroReels requires Python 3.11 to 3.13.
  echo Python 3.14 is not supported yet because of the local TTS runtime.
  pause
  exit /b 1
)
if not exist .venv (
  echo Creating virtual environment with Python %PYVER%...
  py %PYVER% -m venv .venv
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
echo ZeroReels core installed.
echo Open ZeroReels and use the Setup page to install/download the local AI components.
echo.
pause
