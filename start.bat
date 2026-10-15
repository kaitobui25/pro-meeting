@echo off
setlocal
cd /d "%~dp0"

if not defined PRO_MEETING_BROWSER set "PRO_MEETING_BROWSER=neo"

if not exist ".venv\Scripts\python.exe" (
    echo [Pro Meeting] Creating Python environment...
    py -3 -m venv .venv
    if errorlevel 1 goto :failed
)

if not exist ".venv\.ready-local-fast-1" (
    echo [Pro Meeting] Installing dependencies for first launch...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :failed
    type nul > ".venv\.ready-local-fast-1"
)

start "Pro Meeting" ".venv\Scripts\pythonw.exe" "%~dp0boot.py"
exit /b 0

:failed
echo.
echo Setup failed. Check Python 3 installation and Internet connection.
pause
exit /b 1
