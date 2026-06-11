@echo off
:: start.bat – BMEcat Download-Tool starten

set PYTHON=
for %%C in (python py) do (
    if "!PYTHON!"=="" (
        %%C --version >nul 2>&1
        if !errorlevel! == 0 set PYTHON=%%C
    )
)

if "%PYTHON%"=="" (
    echo Python nicht gefunden. Bitte install.bat ausfuehren.
    pause
    exit /b 1
)

%PYTHON% "%~dp0main.py" %*
if errorlevel 1 (
    echo.
    echo Fehler beim Starten. Bitte install.bat erneut ausfuehren.
    pause
)
