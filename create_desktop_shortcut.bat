@echo off
setlocal

cd /d "%~dp0"

set "REPO=%~dp0"
set "TARGET=%~dp0start.bat"

if not exist "%TARGET%" (
  echo [ERROR] start.bat was not found:
  echo   %TARGET%
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$repo=(Resolve-Path $env:REPO).Path; $target=(Resolve-Path $env:TARGET).Path; $desktop=[Environment]::GetFolderPath('Desktop'); $name='LINE' + [char]0x30A2 + [char]0x30A4 + [char]0x30B3 + [char]0x30F3 + [char]0x30E1 + [char]0x30FC + [char]0x30AB + [char]0x30FC + '.lnk'; $path=Join-Path $desktop $name; $shell=New-Object -ComObject WScript.Shell; $shortcut=$shell.CreateShortcut($path); $shortcut.TargetPath=$target; $shortcut.WorkingDirectory=$repo; $shortcut.Description='LINE icon maker launcher'; $shortcut.IconLocation=$env:SystemRoot + '\System32\shell32.dll,44'; $shortcut.Save(); Write-Host ('Created shortcut: ' + $path)"

if errorlevel 1 (
  echo.
  echo [ERROR] Failed to create the desktop shortcut.
  pause
  exit /b 1
)

echo.
echo Done.
pause
