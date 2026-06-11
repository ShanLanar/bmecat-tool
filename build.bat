@echo off
setlocal enabledelayedexpansion
:: build.bat – Erzeugt BMEcat-Tool.exe (kein Python auf Zielrechner nötig)
::
:: WICHTIG fuer Windows Server 2008 / Windows 7:
::   Python 3.8 verwenden! Python 3.9+ erzeugt EXEs die api-ms-win-core-path
::   benoetigen, das auf aelteren Windows-Versionen fehlt.
::   Python 3.8 Download: https://www.python.org/downloads/release/python-3817/
::
:: Ausgabe: dist\BMEcat-Tool.exe

echo ============================================================
echo  BMEcat Download-Tool – EXE-Build
echo ============================================================
echo.

:: Python 3.8 bevorzugen (fuer Windows Server 2008 Kompatibilitaet)
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python38\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python38-32\python.exe"
    "C:\Python38\python.exe"
    "C:\Python38-32\python.exe"
) do ( if exist %%P ( set PYTHON=%%P & goto found ) )

:: Fallback: neuere Python-Version (nur fuer Windows 8.1+)
python --version >nul 2>&1
if %errorlevel% == 0 ( set PYTHON=python & goto found )
py -3.8 --version >nul 2>&1
if %errorlevel% == 0 ( set PYTHON=py -3.8 & goto found )
py --version >nul 2>&1
if %errorlevel% == 0 ( set PYTHON=py & goto found )
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
) do ( if exist %%P ( set PYTHON=%%P & goto found ) )
echo FEHLER: Python nicht gefunden.
pause & exit /b 1

:found
echo Python: %PYTHON%
%PYTHON% --version
echo.

:: Warnung wenn nicht Python 3.8
%PYTHON% -c "import sys; v=sys.version_info; exit(0 if v.major==3 and v.minor==8 else 1)" >nul 2>&1
if %errorlevel% neq 0 (
    echo WARNUNG: Python 3.8 nicht gefunden.
    echo.
    echo  Fuer Windows Server 2008 / Windows 7 gibt es zwei Optionen:
    echo.
    echo  OPTION A (empfohlen, sofort):
    echo    vc_redist.x64.exe auf dem Zielrechner installieren:
    echo    https://aka.ms/vs/17/release/vc_redist.x64.exe
    echo.
    echo  OPTION B (Build mit Python 3.8):
    echo    Python 3.8 installieren: https://www.python.org/downloads/release/python-3817/
    echo    Dann build.bat erneut ausfuehren.
    echo.
    echo  Mit der aktuellen Python-Version wird die EXE trotzdem gebaut,
    echo  laeuft aber nur auf Windows 8.1 / Server 2012 oder neuer.
    echo.
    set /p CONT="Trotzdem weitermachen? (j/n): "
    if /i not "!CONT!"=="j" exit /b 0
    echo.
)

:: Abhängigkeiten installieren
echo Installiere Abhaengigkeiten...
%PYTHON% -m pip install paramiko openpyxl pandas pyinstaller --quiet
echo.

:: Alte Build-Artefakte bereinigen
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

:: Build
echo Starte PyInstaller Build...
%PYTHON% -m PyInstaller ^
  --onefile ^
  --windowed ^
  --name "BMEcat-Tool" ^
  --add-data "config.py;." ^
  --add-data "tasks;tasks" ^
  --add-data "lib;lib" ^
  --add-data "analyse_fnames.py;." ^
  --hidden-import "paramiko" ^
  --hidden-import "paramiko.transport" ^
  --hidden-import "paramiko.sftp_client" ^
  --hidden-import "openpyxl" ^
  --hidden-import "pandas" ^
  --hidden-import "pandas._libs.tslibs.np_datetime" ^
  --hidden-import "pandas._libs.tslibs.nattype" ^
  --hidden-import "pandas._libs.tslibs.timedeltas" ^
  --hidden-import "tkinter" ^
  --hidden-import "tkinter.ttk" ^
  --hidden-import "tkinter.scrolledtext" ^
  --hidden-import "tkinter.filedialog" ^
  --hidden-import "tkinter.messagebox" ^
  --collect-all "paramiko" ^
  --collect-all "openpyxl" ^
  main.py > build_log.txt 2>&1

set BUILD_ERR=%errorlevel%
echo.
if %BUILD_ERR% neq 0 (
    echo FEHLER beim Build! Siehe build_log.txt
    type build_log.txt
) else (
    echo Build erfolgreich.
)

echo.
echo ============================================================
echo  Fertig!  dist\BMEcat-Tool.exe
echo ============================================================
echo.
echo Die EXE laeuft ohne Python-Installation.
echo Benoetigt werden weiterhin:
echo   - 7-Zip unter C:\Program Files\7-Zip\7z.exe
echo   - Bestand_und_Preise.xlsx in C:\bmecat_download\
echo.
echo Fuer Windows Server 2008 / Windows 7:
echo   Falls Fehler "api-ms-win-core-path-l1-1-0.dll fehlt":
echo   vc_redist.x64.exe installieren:
echo   https://aka.ms/vs/17/release/vc_redist.x64.exe
echo.

set /p STARTEXE="EXE jetzt starten? (j/n): "
if /i "%STARTEXE%"=="j" start "" "dist\BMEcat-Tool.exe"

pause

