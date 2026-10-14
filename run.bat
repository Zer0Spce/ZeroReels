@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo ZeroReels is not set up yet. Running setup...
  call setup.bat
)
.venv\Scripts\python.exe -m zeroreels
