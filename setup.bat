@echo off
setlocal

rem Bob Frm Mktg - compatibility setup launcher for Windows

set "DIR=%~dp0"

if exist "%DIR%.venv\Scripts\python.exe" (
  set "PYTHON=%DIR%.venv\Scripts\python.exe"
  goto run
)

if exist "%DIR%runtime\python\python.exe" (
  set "PYTHON=%DIR%runtime\python\python.exe"
  goto run
)

if exist "%DIR%runtime\python\Scripts\python.exe" (
  set "PYTHON=%DIR%runtime\python\Scripts\python.exe"
  goto run
)

if exist "%DIR%.runtime\python\python.exe" (
  set "PYTHON=%DIR%.runtime\python\python.exe"
  goto run
)

if exist "%DIR%.runtime\python\Scripts\python.exe" (
  set "PYTHON=%DIR%.runtime\python\Scripts\python.exe"
  goto run
)

where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  set "PYTHON=python"
  goto run
)

where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  set "PYTHON=py -3"
  goto run
)

echo Bob can't start because this folder does not include a Python runtime.
echo.
echo Use the full Bob release package for your computer, then open that folder in your AI app and say: set me up
exit /b 1

:run
%PYTHON% "%DIR%lib\datapull.py" onboard --interactive
