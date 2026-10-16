@echo off
setlocal EnableDelayedExpansion
:: daten_ziehen.bat
:: 1) Holt den aktuellen Stand von GitHub (git fetch)
:: 2) Wechselt auf den festen Arbeits-Branch (siehe BRANCH unten) und pullt
:: 3) Zeigt Branch, letzten Commit und lokale Aenderungen zur Kontrolle
:: 4) Installiert ggf. neue Abhaengigkeiten (requirements.txt)
::
:: Voraussetzung: Git muss installiert sein (https://git-scm.com)

:: Fester Arbeits-Branch. NICHT automatisch den "neuesten" claude/* Branch
:: waehlen - andere claude/* Branches koennen juengere Commits haben und
:: wuerden den lokalen Stand still umschalten.
set BRANCH=claude/sweet-fermat-wy1fx9

title BMEcat-Tool – Aktualisieren

echo ============================================
echo  BMEcat-Tool: Update von GitHub
echo ============================================
echo.

:: ── 1. Aktuellen Stand holen ─────────────────────────────────────────────────
echo [1/4] Hole Stand von GitHub (Branch %BRANCH%) ...
git -C "%~dp0" fetch origin %BRANCH%
if errorlevel 1 (
    echo WARNUNG: git fetch fehlgeschlagen. Pruefe Netzwerkverbindung.
    echo Weiter mit vorhandener Version ...
    goto :DEPS
)

:: ── 2. Branch wechseln und pullen ────────────────────────────────────────────
echo.
echo [2/4] Wechsle auf %BRANCH% und aktualisiere ...
for /f "tokens=*" %%C in ('git -C "%~dp0" rev-parse --abbrev-ref HEAD 2^>nul') do set CURRENT_BRANCH=%%C
echo   Aktuell : !CURRENT_BRANCH!

if /i not "!CURRENT_BRANCH!"=="%BRANCH%" (
    git -C "%~dp0" checkout -B "%BRANCH%" --track "origin/%BRANCH%"
    if errorlevel 1 (
        echo WARNUNG: Branch-Wechsel fehlgeschlagen - siehe Meldung oben.
    )
)

git -C "%~dp0" pull --ff-only origin %BRANCH%
if errorlevel 1 (
    echo.
    echo WARNUNG: Pull fehlgeschlagen - siehe Git-Meldung oben.
    echo   Haeufigste Ursache: lokal geaenderte Dateien. Lokale Aenderungen
    echo   verwerfen mit:   git -C "%~dp0" checkout -- DATEINAME
    echo   oder alle:       git -C "%~dp0" checkout -- .
)

:: ── 3. Kontrolle ─────────────────────────────────────────────────────────────
echo.
echo [3/4] Stand nach Update:
for /f "tokens=*" %%C in ('git -C "%~dp0" rev-parse --abbrev-ref HEAD 2^>nul') do set CURRENT_BRANCH=%%C
echo   Branch : !CURRENT_BRANCH!
for /f "tokens=*" %%L in ('git -C "%~dp0" log --oneline -1 2^>nul') do echo   Commit : %%L
git -C "%~dp0" status --short --untracked-files=no > "%TEMP%\bmecat_git_status.txt" 2>nul
for %%S in ("%TEMP%\bmecat_git_status.txt") do set STATUS_SIZE=%%~zS
if not "!STATUS_SIZE!"=="0" (
    echo   Lokal geaenderte Dateien ^(blockieren ggf. den naechsten Pull^):
    type "%TEMP%\bmecat_git_status.txt"
)
del "%TEMP%\bmecat_git_status.txt" >nul 2>&1

:: ── 4. Abhaengigkeiten aktualisieren ─────────────────────────────────────────
:DEPS
echo.
echo [4/4] Pruefe Abhaengigkeiten ...
set PYTHON=
for %%C in (python py) do (
    if "!PYTHON!"=="" (
        %%C --version >nul 2>&1
        if !errorlevel! == 0 set PYTHON=%%C
    )
)
if "!PYTHON!"=="" (
    for %%P in (
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
        "C:\Python313\python.exe"
        "C:\Python312\python.exe"
        "C:\Python311\python.exe"
    ) do (
        if "!PYTHON!"=="" if exist %%P set PYTHON=%%P
    )
)
if "!PYTHON!"=="" (
    echo WARNUNG: Python nicht gefunden - Abhaengigkeiten nicht geprueft. Bitte install.bat ausfuehren.
) else if exist "%~dp0requirements.txt" (
    !PYTHON! -m pip install -q -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo WARNUNG: Abhaengigkeiten konnten nicht installiert werden.
    ) else (
        echo   Abhaengigkeiten aktuell.
    )
) else (
    echo   Keine requirements.txt gefunden, uebersprungen.
)

echo.
echo Fertig. Anwendung komplett beenden und mit start.bat neu starten.
echo.
pause
endlocal
