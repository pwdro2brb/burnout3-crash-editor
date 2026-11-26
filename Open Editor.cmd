@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if not errorlevel 1 (
    python -B "%~dp0scripts\editor\run_editor.py" %*
) else (
    where py >nul 2>nul
    if errorlevel 1 (
        echo Python 3.10 or later was not found.
        echo Install Python with Tcl/Tk and open this file again.
        pause
        exit /b 1
    )
    py -3 -B "%~dp0scripts\editor\run_editor.py" %*
)
if errorlevel 1 pause
endlocal
