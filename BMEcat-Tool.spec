# BMEcat-Tool.spec
# PyInstaller Spec-Datei – reproduzierbarer Build
# Verwendung: pyinstaller BMEcat-Tool.spec

block_cipher = None

import sys
from pathlib import Path
ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / 'main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / 'config.py'),          '.'),
        (str(ROOT / 'analyse_fnames.py'),  '.'),
        (str(ROOT / 'tasks'),              'tasks'),
        (str(ROOT / 'lib'),                'lib'),
    ],
    hiddenimports=[
        'paramiko', 'paramiko.transport', 'paramiko.sftp_client',
        'paramiko.sftp_file', 'paramiko.auth_handler', 'paramiko.channel',
        'paramiko.dsskey', 'paramiko.ecdsakey', 'paramiko.ed25519key',
        'paramiko.hostkeys', 'paramiko.kex_curve25519', 'paramiko.kex_ecdh_nist',
        'paramiko.kex_gex', 'paramiko.kex_group1', 'paramiko.kex_group14',
        'paramiko.kex_group16', 'paramiko.packet', 'paramiko.pkey',
        'paramiko.rsakey', 'paramiko.sftp_attr', 'paramiko.util',
        'openpyxl', 'openpyxl.styles', 'openpyxl.utils',
        'openpyxl.workbook', 'openpyxl.worksheet',
        'pandas', 'pandas._libs', 'pandas._libs.tslibs',
        'pandas._libs.tslibs.np_datetime', 'pandas._libs.tslibs.nattype',
        'pandas._libs.tslibs.timedeltas', 'pandas._libs.tslibs.timestamps',
        'tkinter', 'tkinter.ttk', 'tkinter.scrolledtext',
        'tkinter.filedialog', 'tkinter.messagebox', 'tkinter.simpledialog',
        'ftplib', 'csv', 'json', 'pathlib', 'threading', 'subprocess',
        'logging', 'datetime', 'shutil', 'glob', 'importlib', 'inspect',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'scipy', 'PIL', 'IPython',
        'jupyter', 'PyQt5', 'PyQt6', 'wx',
        'test', 'unittest',
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='BMEcat-Tool',
    debug=False,
    strip=False,
    upx=True,
    console=False,      # kein Konsolenfenster
    # icon='icon.ico',  # optional: ICO-Datei einbinden
)
