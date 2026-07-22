@echo off
REM DeciWaves GUI launcher + first-run bootstrap for a git clone.
REM
REM On first run (no repo-local .venv) it creates the virtual environment and
REM installs deciwaves[gui] -- the documented install target -- then launches the
REM GUI. On later runs it just launches. On any failure it stays open so the
REM error is readable instead of the console flashing shut.
setlocal enabledelayedexpansion
cd /d "%~dp0"
set "VENVPY=.venv\Scripts\python.exe"

REM --- 1. Bootstrap the environment on first run -----------------------------
if not exist "%VENVPY%" (
    echo [DeciWaves] First run: no .venv found -- setting up the environment.
    echo.

    REM Find a real base Python to build the venv with. Probe with a trivial
    REM command rather than trusting `where`: the Microsoft Store "python.exe"
    REM app-execution-alias stub is NOT a real interpreter -- it exits non-zero
    REM (or pops the Store) instead of running code, so `where python` finding it
    REM must not be mistaken for Python being installed.
    set "BASEPY="
    py -3 -c "import sys" >nul 2>nul && set "BASEPY=py -3"
    if not defined BASEPY (
        python -c "import sys" >nul 2>nul && set "BASEPY=python"
    )

    if not defined BASEPY (
        echo [DeciWaves] No working Python found.
        echo.
        echo Install Python 3.10+ from https://www.python.org/downloads/
        echo   ^(tick "Add python.exe to PATH" in the installer^), then
        echo double-click this file again.
        echo.
        echo Note: the Microsoft Store "python" shortcut is a stub, not a real
        echo interpreter -- install the python.org build instead.
        echo.
        pause
        exit /b 1
    )

    echo [DeciWaves] Creating virtual environment in .venv ...
    !BASEPY! -m venv .venv
    if errorlevel 1 (
        echo.
        echo [DeciWaves] Failed to create the virtual environment. See the error above.
        echo.
        pause
        exit /b 1
    )

    echo [DeciWaves] Installing DeciWaves + GUI. This can take a few minutes on
    echo             the first run ^(downloads PySide6^)...
    echo.
    "%VENVPY%" -m pip install --upgrade pip
    "%VENVPY%" -m pip install -e ".[gui]"
    if errorlevel 1 (
        echo.
        echo [DeciWaves] Install failed. See the error above. To retry cleanly,
        echo delete the .venv folder and run this file again.
        echo.
        pause
        exit /b 1
    )
    echo.
    echo [DeciWaves] Setup complete -- launching the GUI.
    echo.
)

REM --- 2. Launch ------------------------------------------------------------
"%VENVPY%" -m deciwaves.gui %*
set "RC=%errorlevel%"
if not "%RC%"=="0" (
    echo.
    echo [DeciWaves] GUI exited with error code %RC%.
    echo If this persists, delete the .venv folder and run this file again to
    echo reinstall from scratch.
    echo.
    pause
)
exit /b %RC%
