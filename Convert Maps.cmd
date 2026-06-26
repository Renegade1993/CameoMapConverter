@echo off
setlocal enabledelayedexpansion
REM ====================================================================
REM  Convert Maps.cmd -- launcher for cameo_map_converter.py
REM  * Double-click            -> converts every .oramap in the "maps" folder
REM                               (results in maps\converted)
REM  * Drag a .oramap or folder onto this file -> converts that
REM  Finds Python for you (py launcher, then python, then python3).
REM ====================================================================
cd /d "%~dp0"
set "SCRIPT=cameo_map_converter.py"
set "PY="
where py        >nul 2>&1 && set "PY=py -3"
if not defined PY ( where python  >nul 2>&1 && set "PY=python" )
if not defined PY ( where python3 >nul 2>&1 && set "PY=python3" )
if not defined PY (
    echo.
    echo [ERROR] Python 3 was not found. Install it from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during setup, then run this again.
    echo.
    pause & exit /b 1
)
echo Using interpreter: %PY%
echo.
if "%~1"=="" (
    echo No file dropped -- converting everything in the "maps" folder...
    %PY% "%SCRIPT%" "maps"
) else (
    %PY% "%SCRIPT%" %*
)
echo.
echo Done. Review the output above, then check the "converted" folder.
pause
