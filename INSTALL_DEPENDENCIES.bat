@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python launcher "py" was not found. Install Python 3.11+ first.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" py -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Python dependencies were not installed.
  pause
  exit /b 1
)
echo [OK] Python dependencies installed.
pause
