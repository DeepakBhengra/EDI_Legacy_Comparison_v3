@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist "run_comparison.bat" (
    echo run_comparison.bat was not found next to this installer.
    pause
    exit /b 1
)

set "TARGET=%CD%\run_comparison.bat"
set "WORKDIR=%CD%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$desktop = [Environment]::GetFolderPath('Desktop');" ^
  "$path = Join-Path $desktop 'EDI Comparison.lnk';" ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$s = $ws.CreateShortcut($path);" ^
  "$s.TargetPath = '%TARGET%';" ^
  "$s.WorkingDirectory = '%WORKDIR%';" ^
  "$s.WindowStyle = 1;" ^
  "$s.Description = 'Compare GDL and Legacy EDI files';" ^
  "$s.Save();" ^
  "Write-Host ('Shortcut created: ' + $path)"

if errorlevel 1 (
    echo Could not create the Desktop shortcut.
    pause
    exit /b 1
)

echo.
echo Double-click "EDI Comparison" on your Desktop to run the tool.
echo.
pause
