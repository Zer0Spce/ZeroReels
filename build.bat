@echo off
setlocal
cd /d "%~dp0"
echo Building ZeroReels portable Windows app...
if not exist .venv\Scripts\python.exe call setup.bat
call .venv\Scripts\activate.bat
python -m pip install -e ".[dev]"
python -m PyInstaller --noconfirm --clean ZeroReels.spec
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)
echo.
echo Build complete: dist\ZeroReels\ZeroReels.exe
echo Copy the entire dist\ZeroReels folder when moving the portable app.
pause
