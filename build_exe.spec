# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['cameo_converter_gui.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('cameo_map_converter.py', '.'),
        ('converter_logging.py', '.'),
        ('resource_reclassification.py', '.'),
        ('water_crossing_detect.py', '.'),
        ('minimap_render.py', '.'),
        ('bi_protocol.yaml', '.'),
        ('actor_matrix.yaml', '.'),
        ('template_matrix.yaml', '.'),
        ('cameo_actors.txt', '.'),
        ('converter_config.yaml', '.'),
        ('ra_temperat.yaml', '.'),
        ('README.md', '.'),
        ('QUICKSTART.md', '.'),
        ('CODEBASE_REFERENCE.md', '.'),
        ('DEVELOPER_NOTES.md', '.'),
        ('Icon/cmc.ico', 'Icon'),
    ],
    hiddenimports=[
        'PyQt5',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'PyQt5.sip',
        'socket',
        '_socket',
        'logging.handlers',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['pyi_rth_cameo_isolation.py'],
    excludes=[],
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
    name='CameoMapConverter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Set to True if you want to see console output
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='Icon/cmc.ico',
)
