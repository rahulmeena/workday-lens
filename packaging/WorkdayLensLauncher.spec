# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


project_root = Path.cwd()
entry_script = str(project_root / "launcher" / "main.py")
icon_path = project_root / "packaging" / "assets" / "workday-lens-friendly.ico"

hiddenimports = sorted(
    set(
        collect_submodules("agent")
        + collect_submodules("backend")
        + collect_submodules("launcher")
        + collect_submodules("pkg_resources._vendor")
        + collect_submodules("sqlalchemy.dialects.sqlite")
        + [
            "PIL.Image",
            "PIL.ImageDraw",
            "openai",
            "openai._client",
            "pkg_resources._vendor.jaraco.text",
            "pystray._win32",
            "sqlalchemy.dialects.sqlite.pysqlite",
            "uvicorn.lifespan.on",
            "uvicorn.loops.auto",
            "uvicorn.protocols.http.auto",
            "uvicorn.protocols.websockets.auto",
        ]
    )
)

block_cipher = None


a = Analysis(
    [entry_script],
    pathex=[str(project_root)],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "IPython",
        "datasets",
        "matplotlib",
        "nltk",
        "pandas",
        "pygame",
        "scipy",
        "tensorflow",
        "timm",
        "torch",
        "torchvision",
        "transformers",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WorkdayLensLauncher",
    icon=str(icon_path) if icon_path.exists() else None,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="WorkdayLensLauncher",
)
