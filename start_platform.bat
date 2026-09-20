@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 (
    echo Could not create .venv. Install Python 3 and try again.
    pause
    exit /b 1
  )
)
if not exist ".venv\Lib\site-packages\fastapi\__init__.py" (
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
".venv\Scripts\python.exe" open_platform.py
if errorlevel 1 pause
