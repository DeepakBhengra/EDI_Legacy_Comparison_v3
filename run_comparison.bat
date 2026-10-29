@echo off
setlocal EnableExtensions
title GDL vs Legacy EDI Comparison
cd /d "%~dp0"

if not exist "compare_segments.py" (
    echo This launcher must stay in the project folder, next to compare_segments.py.
    echo Create a Desktop shortcut with install_desktop_shortcut.bat instead of copying this file.
    echo.
    pause
    exit /b 1
)

set "PY="
if exist ".venv\Scripts\python.exe" set "PY=%CD%\.venv\Scripts\python.exe"

if not defined PY (
    where py >nul 2>&1
    if not errorlevel 1 (
        echo Creating .venv ...
        py -3 -m venv .venv
        if exist ".venv\Scripts\python.exe" set "PY=%CD%\.venv\Scripts\python.exe"
    )
)

if not defined PY (
    where python >nul 2>&1
    if not errorlevel 1 (
        echo Creating .venv ...
        python -m venv .venv
        if exist ".venv\Scripts\python.exe" set "PY=%CD%\.venv\Scripts\python.exe"
    )
)

if not defined PY (
    echo Python 3.10 or later was not found.
    echo Install it from https://www.python.org/downloads/
    echo Tick "Add python.exe to PATH", then double-click this file again.
    echo.
    pause
    exit /b 1
)

"%PY%" -c "import xlsxwriter, paramiko" >nul 2>&1
if errorlevel 1 (
    echo Installing packages into .venv. This happens once.
    "%PY%" -m pip install --upgrade pip
    "%PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo pip install failed. In VS Code run: python -m pip install -r requirements.txt
        echo.
        pause
        exit /b 1
    )
)

echo.
echo Starting compare_segments.py
echo Close this window after you have noted the Excel report path.
echo.
"%PY%" compare_segments.py %*
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" echo The comparison exited with code %RC%.
pause
exit /b %RC%
