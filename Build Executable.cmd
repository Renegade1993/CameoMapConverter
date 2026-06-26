@echo off
REM ====================================================================
REM  Build Executable.cmd -- Creates standalone CameoMapConverter.exe
REM  Requires: Python 3 and PyInstaller (pip install pyinstaller)
REM  Output: CameoMapConverter.exe (single file, no dependencies)
REM ====================================================================

cd /d "%~dp0"

echo Checking for PyInstaller...
py -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo PyInstaller not found. Installing...
    py -m pip install pyinstaller
)

echo.
echo Building CameoMapConverter.exe...
py -m PyInstaller build_exe.spec

if errorlevel 1 (
    echo.
    echo Build failed! Check the error messages above.
    pause
    exit /b 1
)

echo.
echo Moving executable to current directory...
if exist "dist\CameoMapConverter.exe" (
    move /Y "dist\CameoMapConverter.exe" "CameoMapConverter.exe"
    if exist "dist" rmdir /S /Q "dist"
    if exist "build" rmdir /S /Q "build"
)

echo.
echo Build successful!
echo Executable location: CameoMapConverter.exe
echo.
echo You can now distribute CameoMapConverter.exe to users
echo without requiring Python installation.
echo.
pause
