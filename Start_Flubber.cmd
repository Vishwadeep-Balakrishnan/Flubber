@echo off
setlocal
cd /d "%~dp0companion"
if not exist .venv\Scripts\python.exe (
  py -3.12 -m venv .venv
  if errorlevel 1 py -3 -m venv .venv
)
if not exist .venv\Scripts\python.exe (
  echo Install Python 3.12 from python.org, then run this again.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -c "import sys; assert sys.version_info >= (3,11), 'Install Python 3.12 or newer.'"
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto fail
.venv\Scripts\python.exe configure.py --if-missing
if errorlevel 1 goto fail
.venv\Scripts\python.exe run.py
if errorlevel 1 goto fail
exit /b 0
:fail
echo Flubber could not start. Read the message above.
pause
exit /b 1
