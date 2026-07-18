@echo off
REM DeciWaves GUI launcher for running from a git clone.
REM Prefers the repo-local .venv (the documented install target); falls back to
REM a global Python. On any failure it stays open so the error is readable
REM instead of the console flashing shut.
setlocal
set "HERE=%~dp0"

set "PYEXE="
if exist "%HERE%.venv\Scripts\python.exe" (
    set "PYEXE=%HERE%.venv\Scripts\python.exe"
) else (
    where py     >nul 2>nul && set "PYEXE=py"
    if not defined PYEXE where python >nul 2>nul && set "PYEXE=python"
)

if not defined PYEXE (
    echo.
    echo [DeciWaves] No Python found.
    echo Create the project environment first, from the repo root:
    echo     python -m venv .venv
    echo     .venv\Scripts\python -m pip install -e ".[gui]"
    echo then double-click this file again.
    echo.
    pause
    exit /b 1
)

"%PYEXE%" -m deciwaves.gui %*
set "RC=%errorlevel%"
if not "%RC%"=="0" (
    echo.
    echo [DeciWaves] GUI exited with error code %RC%.
    echo If the error above is "No module named ...", install the GUI extra:
    echo     "%PYEXE%" -m pip install -e ".[gui]"
    echo.
    pause
)
exit /b %RC%
