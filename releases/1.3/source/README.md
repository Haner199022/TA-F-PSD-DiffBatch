# TA-F PSD DiffBatch (cross-platform)

Tkinter GUI launcher that drives Photoshop in the background to batch-normalize
PSDs against a reference file. Same Python codebase builds to a Mac `.app` and
a Windows `.exe`.

## Layout

```
app/
├── launcher.py        # Tkinter GUI entry point (two tabs)
├── ps_driver.py       # Drives Photoshop via osascript (Mac) or COM (Win)
├── normalize_psd.jsx  # PSD Normalizer ExtendScript (bundled)
├── scripts/           # Bundled .jsx scripts for Script Runner tab
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

The GUI has two tabs sharing the same status bar, progress, and log output.

### Tab 1 — Normalizer

1. User picks **After** (reference) PSD, optional **Before** PSD, and a batch
   folder.
2. **Analyze** — generates a temp wrapper `.jsx` that sets the analyze
   automation hook, asks Photoshop to run it, reads the JSON result.
3. **Run batch** — same pattern with the batch hook; live log lines are tailed
   from `<batch folder>/../_normalized/normalize_log.txt` while PS works.
4. Outputs land next to the source folder as a sibling `_normalized/` directory.
   Originals are never touched.

### Tab 2 — Script Runner

Run any user-supplied `.jsx` against every PSD in a folder.

1. Pick a script from the dropdown (bundled `scripts/` + any user-added dirs)
   or click **Browse** for a one-off. **+ Dir** adds a folder of scripts that
   the launcher remembers across runs (saved in `~/.tafpsd_presets.json`).
2. Optional — click **+ Add** to queue multiple scripts. Each queued script
   runs as its own pass over the whole batch folder, in order. **Clear** wipes
   the queue. If the queue is empty, RUN uses just the dropdown selection.
3. Pick the **Batch folder** (shared with Tab 1).
4. Pick **Output mode**:
   - *Save to output* (default) — saves a copy of each PSD into the Output
     folder (or `<batch>/../_script_out/`). Originals untouched.
   - *Overwrite* — `save()` over the source PSD.
   - *Don't save* — close without saving. Use this when the script itself
     exports something (e.g. saves PNG/JPG slices).
5. Click **RUN SCRIPT**. The launcher opens each PSD, evals your script
   against `app.activeDocument`, then saves/closes per the mode.

**Queue semantics**

Each queued script gets its own pass — the launcher does *not* keep the PSD
open between scripts. If you queue `A` then `B` with Output mode *Save to
output*, `B`'s pass reopens the source PSDs (not `A`'s output), and B's saves
overwrite A's same-name copies. To chain scripts where each builds on the
previous: use *Overwrite* mode so each pass reads the previous pass's result
from the source file.

**Writing a custom script**

Your `.jsx` should just operate on `app.activeDocument` — do **not** call
`save()` or `close()` yourself, the wrapper handles that. Errors in a single
PSD are logged and the batch continues. See `app/scripts/_example_flatten.jsx`
for a minimal example.

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
