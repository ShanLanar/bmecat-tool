# BMEcat Download-Tool

Python-Neubau der `bmecat-download.bat` + `BestandsdatenErzeugen_noxls.ps1`.

## Voraussetzungen

- Python 3.9+
- 7-Zip installiert unter `C:\Program Files\7-Zip\7z.exe`
- `pip install -r requirements.txt`  (installiert `paramiko` für SFTP)

## Starten

```bat
python main.py
```

## Projektstruktur

```
bmecat_tool/
│
├── main.py                  GUI-Einstiegspunkt (tkinter)
├── config.py                Alle Pfade + FTP/SFTP-Zugangsdaten
├── requirements.txt
│
├── lib/
│   ├── ftp_client.py        FTPClient / SFTPClient (WinSCP-Ersatz)
│   └── bestandsdaten.py     Port von BestandsdatenErzeugen_noxls.ps1
│
└── tasks/
    ├── bueroring.py         Büroring: Download + Bestand + Mercateo-Upload
    ├── nordwest.py          Nordwest: BMEcat-ZIPs + KIP-CSV
    ├── softcarrier.py       Softcarrier: Lagerbestand + BMEcat
    ├── systeam.py           Systeam: BMECAT ZIP
    └── others.py            Mercateo-Upload, Soennecken, Bilder-Upload
```

## Zugangsdaten anpassen

Alle FTP/SFTP-Zugangsdaten und lokalen Pfade zentral in **`config.py`** pflegen.
Kein Neustart der GUI nötig – Änderungen werden beim nächsten Task-Start geladen.

## Aufgaben einzeln ausführen

Jede `tasks/*.py`-Datei exportiert eine `run(progress_cb=None)`-Funktion,
die auch direkt aus der Python-Konsole aufrufbar ist:

```python
from tasks.bueroring import run
run()
```

## Log

Tägliche Log-Datei unter `C:\bmecat_download\logs\Log_YYYYMMDD.txt`.
