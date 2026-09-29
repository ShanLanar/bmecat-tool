@echo off
setlocal enabledelayedexpansion
:: start.bat – BMEcat Download-Tool starten

set PYTHON=
for %%C in (python py) do (
    if "!PYTHON!"=="" (
        %%C --version >nul 2>&1
        if !errorlevel! == 0 set PYTHON=%%C
    )
)

if "!PYTHON!"=="" (
    :: Nicht auf PATH (z.B. neues Windows-Benutzerkonto, in dem Python nur
    :: unter dem PATH eines anderen Kontos installiert/gefunden wurde) -
    :: dieselben Fallback-Pfade wie install.bat probieren.
    for %%P in (
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
        "C:\Python313\python.exe"
        "C:\Python312\python.exe"
        "C:\Python311\python.exe"
    ) do (
        if "!PYTHON!"=="" if exist %%P (
            set PYTHON=%%P
        )
    )
)

if "!PYTHON!"=="" (
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
