@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo .venv missing. Nothing to stop.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" stop_platform.py
pause
