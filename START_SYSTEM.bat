@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Dependencies are not installed yet.
  echo Run INSTALL_DEPENDENCIES.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
start "" http://127.0.0.1:8000
python main.py
pause
