"""py2app build config for TA-F PSD DiffBatch.

Build:
    pip3 install --user py2app
    cd app/
    python3 setup.py py2app

Result:  dist/TA-F PSD DiffBatch.app  (double-clickable on Mac)
"""
from setuptools import setup

APP = ["launcher.py"]
DATA_FILES = ["normalize_psd.jsx"]

OPTIONS = {
    "argv_emulation": False,  # set True if you want to drag-drop files onto the app icon
    "iconfile": None,
    "plist": {
        "CFBundleName": "TA-F PSD DiffBatch",
        "CFBundleDisplayName": "TA-F PSD DiffBatch",
        "CFBundleIdentifier": "com.cucailab.tafdiffbatch",
        "CFBundleVersion": "1.0",
        "CFBundleShortVersionString": "1.0",
        "NSHumanReadableCopyright": "CUC AI Lab",
        "NSHighResolutionCapable": True,
        # Photoshop is the worker; we shell out to osascript so no special perms needed.
    },
    "packages": [],
    "includes": ["tkinter"],
    # Bundle the JSX next to the Python entrypoint so find_normalize_jsx() finds it.
    "resources": ["normalize_psd.jsx"],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
