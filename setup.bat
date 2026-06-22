@echo off
setlocal

rem Bob Frm Mktg - compatibility setup launcher for Windows

set "DIR=%~dp0"
set "PYTHON_VERSION=3.12.10"
set "RUNTIME_DIR=%DIR%runtime\python"

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

call :bootstrap_python
if errorlevel 1 exit /b 1

if exist "%DIR%runtime\python\python.exe" (
  set "PYTHON=%DIR%runtime\python\python.exe"
  goto run
)

echo Bob still couldn't find a usable Python runtime.
exit /b 1

:run
if "%~1"=="" (
  %PYTHON% "%DIR%lib\datapull.py" onboard --interactive
  exit /b %ERRORLEVEL%
)

%PYTHON% "%DIR%lib\datapull.py" %*
exit /b %ERRORLEVEL%

:bootstrap_python
set "ARCH=%PROCESSOR_ARCHITECTURE%"
set "INSTALLER_NAME=python-%PYTHON_VERSION%-amd64.exe"
if /I "%ARCH%"=="ARM64" set "INSTALLER_NAME=python-%PYTHON_VERSION%-arm64.exe"

set "INSTALLER_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/%INSTALLER_NAME%"
set "INSTALLER_PATH=%TEMP%\%INSTALLER_NAME%"

echo Bob couldn't find Python. Downloading Python %PYTHON_VERSION% from python.org...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -UseBasicParsing '%INSTALLER_URL%' -OutFile '%INSTALLER_PATH%'"
if errorlevel 1 (
  echo Bob couldn't download Python automatically.
  exit /b 1
)

echo Installing a local Python runtime for Bob...
if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%"
"%INSTALLER_PATH%" /quiet InstallAllUsers=0 Include_launcher=0 PrependPath=0 Include_test=0 Include_pip=1 Include_doc=0 Include_tcltk=0 Shortcuts=0 SimpleInstall=1 TargetDir="%RUNTIME_DIR%"
if errorlevel 1 (
  echo Bob downloaded Python but couldn't install it automatically.
  exit /b 1
)

del /q "%INSTALLER_PATH%" >nul 2>nul
if exist "%RUNTIME_DIR%\python.exe" exit /b 0

echo Bob installed Python but couldn't find the interpreter afterward.
exit /b 1
