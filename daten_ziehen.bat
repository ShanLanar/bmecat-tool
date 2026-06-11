@echo off
setlocal EnableDelayedExpansion
:: daten_ziehen.bat
:: 1) Holt alle Remote-Branches (git fetch)
:: 2) Wechselt automatisch auf den neuesten claude/* Branch
:: 3) Installiert ggf. neue Abhaengigkeiten
:: 4) Startet alle Standard-Downloads automatisch
::
:: Voraussetzung: Git muss installiert sein (https://git-scm.com)

title BMEcat-Tool – Aktualisieren & Starten

echo ============================================
echo  BMEcat-Tool: Update ^& Daten ziehen
echo ============================================
echo.

:: ── 1. Alle Branches holen ───────────────────────────────────────────────────
echo [1/4] Suche neuesten Branch ...
git -C "%~dp0" fetch --all --prune >nul 2>&1
if errorlevel 1 (
    echo WARNUNG: git fetch fehlgeschlagen. Pruefe Netzwerkverbindung.
    echo Starte mit vorhandener Version ...
    goto :DEPS
)

:: Neuesten claude/* Branch anhand des letzten Commits ermitteln
for /f "tokens=*" %%B in ('git -C "%~dp0" branch -r --sort=-committerdate --list "origin/claude/*" 2^>nul') do (
    if "!NEWEST_REMOTE!"=="" set NEWEST_REMOTE=%%B
)

:: Fallback: main oder master
if "!NEWEST_REMOTE!"=="" (
    git -C "%~dp0" show-ref --verify --quiet refs/remotes/origin/main 2>nul && set NEWEST_REMOTE=origin/main
)
if "!NEWEST_REMOTE!"=="" (
    git -C "%~dp0" show-ref --verify --quiet refs/remotes/origin/master 2>nul && set NEWEST_REMOTE=origin/master
)

if "!NEWEST_REMOTE!"=="" (
    echo WARNUNG: Kein passender Remote-Branch gefunden.
    goto :DEPS
)

:: Lokalen Branch-Namen ableiten (origin/ entfernen und Leerzeichen trimmen)
set LOCAL_BRANCH=!NEWEST_REMOTE!
set LOCAL_BRANCH=!LOCAL_BRANCH:origin/=!
for /f "tokens=* delims= " %%T in ("!LOCAL_BRANCH!") do set LOCAL_BRANCH=%%T

:: Aktuellen Branch ermitteln
for /f "tokens=*" %%C in ('git -C "%~dp0" rev-parse --abbrev-ref HEAD 2^>nul') do set CURRENT_BRANCH=%%C

echo   Aktuell  : !CURRENT_BRANCH!
echo   Neuester : !LOCAL_BRANCH!

if /i "!CURRENT_BRANCH!"=="!LOCAL_BRANCH!" (
    echo   Bereits auf dem neuesten Branch.
) else (
    echo   Wechsle zu !LOCAL_BRANCH! ...
    git -C "%~dp0" checkout -B "!LOCAL_BRANCH!" --track "!NEWEST_REMOTE!" >nul 2>&1
    if errorlevel 1 (
        echo WARNUNG: Branch-Wechsel fehlgeschlagen.
    ) else (
        echo   Branch-Wechsel OK.
    )
)

:: Aktuellen Branch pullen
git -C "%~dp0" pull --ff-only >nul 2>&1
if errorlevel 1 (
    echo WARNUNG: Pull fehlgeschlagen ^(evtl. lokale Aenderungen vorhanden^).
) else (
    echo   Auf aktuellem Stand.
)
echo.

:: ── 2. Abhaengigkeiten aktualisieren ─────────────────────────────────────────
:DEPS
echo [2/4] Pruefe Abhaengigkeiten ...
if exist "%~dp0requirements.txt" (
    pip install -q -r "%~dp0requirements.txt" 2>&1
    if errorlevel 1 (
        echo WARNUNG: Abhaengigkeiten konnten nicht installiert werden.
    ) else (
        echo Abhaengigkeiten aktuell.
    )
) else (
    echo Keine requirements.txt gefunden, uebersprungen.
)
echo.

echo Fertig. Starte die Anwendung manuell mit start.bat

endlocal
