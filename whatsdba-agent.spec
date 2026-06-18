# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec — WhatsDBA Agent
# Build: pyinstaller whatsdba-agent.spec
#
# Gera: dist/whatsdba-agent.exe (single-file, sem Python necessário)

import os
from PyInstaller.utils.hooks import collect_all

# Coleta dados do pyodbc (drivers ODBC)
pyodbc_datas, pyodbc_binaries, pyodbc_hiddenimports = collect_all('pyodbc')

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=pyodbc_binaries,
    datas=[
        ('.env.example', '.'),          # template de configuração
        ('collectors', 'collectors'),   # módulos de coleta
    ] + pyodbc_datas,
    hiddenimports=[
        'pyodbc',
        'pymysql',
        'pymysql.connections',
        'pymysql.cursors',
        'requests',
        'schedule',
        'dotenv',
        'collectors.sqlserver',
        'collectors.mysql',
    ] + pyodbc_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'numpy', 'PIL',
        'scipy', 'pandas', 'IPython', 'jupyter',
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='whatsdba-agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,           # mantém console para logs visíveis
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,              # coloque 'assets/icon.ico' se tiver ícone
    version=None,
)
