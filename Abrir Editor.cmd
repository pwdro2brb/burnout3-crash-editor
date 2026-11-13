@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if not errorlevel 1 (
    python -B "%~dp0scripts\editor\run_editor.py" %*
) else (
    where py >nul 2>nul
    if errorlevel 1 (
        echo Python 3.10 ou posterior nao foi encontrado.
        echo Instale o Python com Tcl/Tk e abra este arquivo novamente.
        pause
        exit /b 1
    )
    py -3 -B "%~dp0scripts\editor\run_editor.py" %*
)
if errorlevel 1 pause
endlocal
