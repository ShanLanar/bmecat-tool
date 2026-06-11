@echo off
setlocal enabledelayedexpansion

:: ============================================================
::  BMEcat Download-Tool – Einrichtung und Abhängigkeiten
::  Führt alle nötigen Schritte für eine saubere Installation
::  durch. Muss einmalig (oder nach Updates) ausgeführt werden.
:: ============================================================

echo.
echo  ****************************************************
echo  *   BMEcat Download-Tool - Einrichtung             *
echo  ****************************************************
echo.

:: ── 1. Python suchen ─────────────────────────────────────────
echo [1/6] Suche Python...

set PYTHON=
set PYTHON_OK=0

for %%C in (python py) do (
    if "!PYTHON!"=="" (
        %%C --version >nul 2>&1
        if !errorlevel! == 0 (
            set PYTHON=%%C
        )
    )
)

if "!PYTHON!"=="" (
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
    echo.
    echo  FEHLER: Python nicht gefunden.
    echo.
    echo  Bitte Python 3.10 oder neuer installieren:
    echo    https://www.python.org/downloads/
    echo.
    echo  Beim Installieren unbedingt anhaeken:
    echo    [x] Add python.exe to PATH
    echo.
    pause
    exit /b 1
)

echo  Python gefunden: !PYTHON!
!PYTHON! --version

:: Python-Version prüfen (mind. 3.9)
!PYTHON! -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>&1
if errorlevel 1 (
    echo.
    echo  FEHLER: Python 3.9 oder neuer erforderlich.
    !PYTHON! --version
    pause
    exit /b 1
)
echo  Version OK.
echo.

:: ── 2. 7-Zip prüfen ──────────────────────────────────────────
echo [2/6] Suche 7-Zip...

set SEVENZIP=
for %%Z in (
    "C:\Program Files\7-Zip\7z.exe"
    "C:\Program Files (x86)\7-Zip\7z.exe"
) do (
    if "!SEVENZIP!"=="" if exist %%Z (
        set SEVENZIP=%%Z
    )
)

if "!SEVENZIP!"=="" (
    echo  WARNUNG: 7-Zip nicht gefunden.
    echo  Ohne 7-Zip koennen keine ZIP-Archive entpackt werden.
    echo.
    echo  Bitte installieren: https://www.7-zip.org/
    echo  Standard-Pfad: C:\Program Files\7-Zip\7z.exe
    echo.
    echo  Installation wird fortgesetzt - 7-Zip kann spaeter nachinstalliert werden.
    echo.
) else (
    echo  7-Zip gefunden: !SEVENZIP!
    echo.
)

:: ── 3. pip aktualisieren ──────────────────────────────────────
echo [3/6] Aktualisiere pip...
!PYTHON! -m ensurepip --upgrade >nul 2>&1
!PYTHON! -m pip install --upgrade pip --quiet
echo  pip OK.
echo.

:: ── 4. Abhängigkeiten installieren ───────────────────────────
echo [4/6] Installiere Abhaengigkeiten...
echo.

set DEPS_OK=1

:: paramiko – SFTP-Bibliothek
echo  - paramiko (SFTP)...
!PYTHON! -m pip install "paramiko>=3.4.0" --quiet
if errorlevel 1 ( echo    FEHLER! & set DEPS_OK=0 ) else ( echo    OK )

:: openpyxl – Excel-Dateien lesen/schreiben
echo  - openpyxl (Excel)...
!PYTHON! -m pip install "openpyxl>=3.1.0" --quiet
if errorlevel 1 ( echo    FEHLER! & set DEPS_OK=0 ) else ( echo    OK )

:: pandas – Datenverarbeitung
echo  - pandas (Datenverarbeitung)...
!PYTHON! -m pip install "pandas>=2.0.0" --quiet
if errorlevel 1 ( echo    FEHLER! & set DEPS_OK=0 ) else ( echo    OK )

:: chardet – Encoding-Erkennung (optional aber empfohlen)
echo  - chardet (Encoding-Erkennung)...
!PYTHON! -m pip install "chardet>=5.0.0" --quiet
if errorlevel 1 ( echo    Warnung: chardet nicht installiert (optional) ) else ( echo    OK )

:: pywin32 – Windows-Integration
echo  - pywin32 (Windows-Scheduler)...
!PYTHON! -m pip install "pywin32>=306" --quiet
if errorlevel 1 ( echo    Warnung: pywin32 nicht installiert (Scheduler benoetigt dies) ) else ( echo    OK )

echo.
if !DEPS_OK!==0 (
    echo  FEHLER: Einige Pakete konnten nicht installiert werden.
    echo  Bitte Internetverbindung pruefen und install.bat erneut ausfuehren.
    pause
    exit /b 1
)

:: ── 5. Verzeichnisse anlegen ──────────────────────────────────
echo [5/6] Lege Verzeichnisse an...

set BASE=%~dp0
for %%D in (
    "%BASE%in_BME"
    "%BASE%in_BME\soc_bilder"
    "%BASE%in"
    "%BASE%in2"
    "%BASE%in_vertrieb"
    "%BASE%logs"
    "%BASE%logs\diff_backups"
    "%BASE%logs\xml_backups"
    "%BASE%sql"
) do (
    if not exist %%D (
        mkdir %%D >nul 2>&1
        echo  Erstellt: %%D
    )
)
echo  Verzeichnisse OK.
echo.

:: ── 6. Installation prüfen ────────────────────────────────────
echo [6/6] Pruefe Installation...

!PYTHON! -c "import paramiko, openpyxl, pandas; print('  Alle Pflicht-Pakete geladen.')"
if errorlevel 1 (
    echo  FEHLER bei der Pruefung!
    pause
    exit /b 1
)

echo.
echo  ****************************************************
echo  *   Installation abgeschlossen!                    *
echo  ****************************************************
echo.
echo  Naechste Schritte:
echo.
echo  1. Bestand_und_Preise.xlsx in diesen Ordner kopieren
echo     (%BASE%)
echo.
echo  2. Zugangsdaten in config.py eintragen (falls noch
echo     nicht geschehen) oder per GUI konfigurieren.
echo.
echo  3. Programm starten mit:
echo     start.bat
echo.

pause
