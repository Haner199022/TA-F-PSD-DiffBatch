# TA-F PSD DiffBatch (cross-platform)

Tkinter GUI launcher that drives Photoshop in the background to batch-normalize
PSDs against a reference file. Same Python codebase builds to a Mac `.app` and
a Windows `.exe`.

## Layout

```
app/
├── launcher.py        # Tkinter GUI entry point
├── ps_driver.py       # Drives Photoshop via osascript (Mac) or COM (Win)
├── normalize_psd.jsx  # The ExtendScript brain (bundled into the build)
├── requirements.txt   # Build deps (pyinstaller + pywin32 on Win)
├── setup.py           # py2app config (Mac, alternative to PyInstaller)
└── README.md          # this file
```

## Run in dev mode (any platform)

```bash
cd app/
python3 launcher.py
```

Requires: Python 3.9+, Photoshop installed locally.
On Windows: also `pip install pywin32`.

## Build a distributable (recommended: PyInstaller, both platforms)

```bash
pip install -r requirements.txt
```

### Mac → `.app`

```bash
cd app/
pyinstaller --windowed --name "TA-F PSD DiffBatch" \
            --add-data "normalize_psd.jsx:." \
            --add-data "assets:assets" \
            --collect-data customtkinter \
            --collect-all tkinterdnd2 launcher.py
```

Output: `dist/TA-F PSD DiffBatch.app`

First launch on a recipient Mac is blocked by Gatekeeper because the bundle is
unsigned — right-click → **Open** the first time, then click **Open** in the
prompt. (Or sign + notarize if you have an Apple Developer cert.)

### Windows → `.exe`

```bat
cd app
pyinstaller --windowed --name "TA-F PSD DiffBatch" ^
            --add-data "normalize_psd.jsx;." ^
            --add-data "assets;assets" ^
            --collect-data customtkinter ^
            --collect-all tkinterdnd2 launcher.py
```

Note the `;` separator between source and dest in `--add-data` (Windows uses
`;`, Mac/Linux use `:`).

Output: `dist\TA-F PSD DiffBatch\TA-F PSD DiffBatch.exe` (folder mode — distribute the
whole folder).

For a single-file `.exe`, add `--onefile` (slower startup, simpler hand-off).

## How it works

1. User picks **After** (reference) PSD, optional **Before** PSD, and a batch
   folder.
2. **Analyze** — generates a temp wrapper `.jsx` that sets the analyze
   automation hook, asks Photoshop to run it, reads the JSON result.
3. **Run batch** — same pattern with the batch hook; live log lines are tailed
   from `<batch folder>/../_normalized/normalize_log.txt` while PS works.
4. Outputs land next to the source folder as a sibling `_normalized/` directory.
   Originals are never touched.

The driver dispatches per OS:

- **macOS**: `osascript` → AppleScript `tell ... do javascript "$.evalFile(...)"`
- **Windows**: `pywin32` → COM `Photoshop.Application.DoJavaScript(...)`

## Distributing

The build is portable but the receiving machine must have:

- Same OS family + architecture as the build (build on each target).
- Photoshop installed (any reasonably modern version with ExtendScript).
- **Mac**: AppleScript permission to control Photoshop — System Settings →
  Privacy → Automation, allow the app to control Photoshop.
- **Windows**: nothing extra — COM is built into the OS.
