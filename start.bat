@echo off
setlocal

cd /d "%~dp0"

set "APP_URL=http://127.0.0.1:5000/"
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"

echo ========================================
echo LINE Icon Maker
echo ========================================
echo.

if not exist "%PYTHON_EXE%" (
  echo [ERROR] Python was not found at:
  echo   %PYTHON_EXE%
  echo.
  echo Create the virtual environment and install dependencies first:
  echo   py -m venv .venv
  echo   .venv\Scripts\python.exe -m pip install -e .[dev]
  echo.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "exit (Test-NetConnection -ComputerName 127.0.0.1 -Port 5000 -InformationLevel Quiet)"
if "%ERRORLEVEL%"=="1" (
  echo [INFO] The app already seems to be running.
  echo Opening %APP_URL%
  start "" "%APP_URL%"
  echo.
  echo If the page does not load, close the other server window and run this file again.
  pause
  exit /b 0
)

echo [INFO] Starting the app with:
echo   %PYTHON_EXE% run.py
echo.
echo [INFO] Browser will open automatically.
echo [INFO] Keep this window open while using the app.
echo.

start "" powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 2; Start-Process '%APP_URL%'"
"%PYTHON_EXE%" run.py

echo.
echo [INFO] The app has stopped.
pause
