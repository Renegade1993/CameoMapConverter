@echo off
REM ====================================================================
REM  Create Distribution.cmd -- Beta v0.76 minimalist distribution builder
REM
REM  Assembles Distribution\Release\ with:
REM    - CameoMapConverter.exe (build it first via "Build Executable.cmd")
REM    - README.md (comprehensive landing page + user manual + release notes)
REM    - QUICKSTART.md (quick reference)
REM
REM  NOTE: run this on Windows from the project folder. It copies the real
REM  project files; do not assemble the package from inside the Cowork sandbox
REM  (its file mirror can be stale -- see CLAUDE.md).
REM ====================================================================

cd /d "%~dp0"

set VERSION=0.76-beta-hotfix1
set DIST_DIR=Distribution
set RELEASE_DIR=%DIST_DIR%\Release
set SRC_DIST_DIR=%DIST_DIR%\source

echo.
echo ========================================
echo Cameo Map Converter Distribution Builder
echo Version: %VERSION%
echo ========================================
echo.

REM ---- Clean previous distribution ----
if exist "%DIST_DIR%" (
    echo Cleaning previous distribution...
    rmdir /S /Q "%DIST_DIR%"
)

REM ---- Directory structure ----
echo Creating directory structure...
mkdir "%RELEASE_DIR%" 2>nul

REM ---- Executable ----
echo Copying executable...
if exist "CameoMapConverter.exe" (
    copy /Y "CameoMapConverter.exe" "%RELEASE_DIR%\" >nul
    echo   - CameoMapConverter.exe
) else (
    echo   WARNING: CameoMapConverter.exe not found.
    echo            Run "Build Executable.cmd" first, then re-run this script.
)

REM ---- Top-level docs (landing page + quick start) ----
echo Copying top-level documentation...
copy /Y "README.md"       "%RELEASE_DIR%\README.md" >nul 2>&1 && echo   - README.md
copy /Y "QUICKSTART.md"   "%RELEASE_DIR%\QUICKSTART.md" >nul 2>&1 && echo   - QUICKSTART.md
copy /Y "LICENSE"         "%RELEASE_DIR%\LICENSE" >nul 2>&1 && echo   - LICENSE

REM ---- Source and tests excluded from Release (for now) ----
echo Skipping source and tests from Release (exe-only distribution)

REM ---- Copy source to Distribution/source (separate from Release) ----
echo Copying source to Distribution\source...
mkdir "%SRC_DIST_DIR%" 2>nul
for %%F in (
    cameo_converter_gui.py
    cameo_map_converter.py
    converter_logging.py
    resource_reclassification.py
    water_crossing_detect.py
    minimap_render.py
    validate_resource_distribution.py
    bi_protocol.yaml
    actor_matrix.yaml
    template_matrix.yaml
    cameo_actors.txt
    converter_config.yaml
    requirements.txt
    pyproject.toml
    build_exe.spec
    pyi_rth_cameo_isolation.py
    "Build Executable.cmd"
    ra_temperat.yaml
) do (
    copy /Y %%F "%SRC_DIST_DIR%\" >nul 2>&1 && echo   - %%~F
)

REM ---- Copy technical docs to source distribution (not the end-user Release) ----
echo Copying technical docs to Distribution\source\docs...
if not exist "%SRC_DIST_DIR%\docs" mkdir "%SRC_DIST_DIR%\docs" 2>nul
for %%F in (
    CODEBASE_REFERENCE.md
    DEVELOPER_NOTES.md
) do (
    copy /Y %%F "%SRC_DIST_DIR%\docs\" >nul 2>&1 && echo   - docs\%%~F
)

REM ---- Copy user docs to source distribution too ----
echo Copying user docs to Distribution\source...
for %%F in (
    README.md
    QUICKSTART.md
) do (
    copy /Y %%F "%SRC_DIST_DIR%\" >nul 2>&1 && echo   - %%~F
)

REM ---- Copy project/legal docs to source distribution ----
echo Copying project and legal docs to Distribution\source...
copy /Y "LICENSE"           "%SRC_DIST_DIR%\LICENSE" >nul 2>&1 && echo   - LICENSE
copy /Y "DEVELOPMENT_LOG.md" "%SRC_DIST_DIR%\DEVELOPMENT_LOG.md" >nul 2>&1 && echo   - DEVELOPMENT_LOG.md
copy /Y "CLAUDE.md"         "%SRC_DIST_DIR%\CLAUDE.md" >nul 2>&1 && echo   - CLAUDE.md
copy /Y ".gitignore"        "%SRC_DIST_DIR%\.gitignore" >nul 2>&1 && echo   - .gitignore

REM ---- Copy dev_tools folder (diagnostic scripts, not required at runtime) ----
echo Copying dev_tools to Distribution\source...
if exist dev_tools (
    xcopy /E /I /Y dev_tools "%SRC_DIST_DIR%\dev_tools" >nul 2>&1 && echo   - dev_tools\
)

REM ---- Copy tests folder ----
echo Copying tests to Distribution\source...
if exist tests (
    xcopy /E /I /Y tests "%SRC_DIST_DIR%\tests" >nul 2>&1 && echo   - tests\
)

REM ---- Create source zip alongside release zip ----
echo Creating source zip...
set SOURCE_ZIP=%DIST_DIR%\CameoMapConverter_v%VERSION%_source.zip
if exist "%SOURCE_ZIP%" del /F "%SOURCE_ZIP%"
powershell -NoProfile -Command "Compress-Archive -Path '%SRC_DIST_DIR%\*' -DestinationPath '%SOURCE_ZIP%'"
if exist "%SOURCE_ZIP%" (
    echo   - %SOURCE_ZIP%
) else (
    echo   WARNING: source zip creation failed.
)

echo.
echo ========================================
echo Distribution package created.
echo ========================================
echo Location: %RELEASE_DIR%\.
echo Source zip: %SOURCE_ZIP%
echo.
REM ---- Create release zip ----
echo Creating release zip...
set RELEASE_ZIP=%DIST_DIR%\CameoMapConverter_v%VERSION%.zip
if exist "%RELEASE_ZIP%" del /F "%RELEASE_ZIP%"
powershell -NoProfile -Command "Compress-Archive -Path '%RELEASE_DIR%\*' -DestinationPath '%RELEASE_ZIP%'"
if exist "%RELEASE_ZIP%" (
    echo   - %RELEASE_ZIP%
) else (
    echo   WARNING: release zip creation failed.
)

echo.
echo ========================================
echo Distribution package created.
echo ========================================
echo Release zip: %RELEASE_ZIP%
echo Source zip: %SOURCE_ZIP%
echo.
