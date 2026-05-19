# TA-F PSD DiffBatch (Windows)

Tkinter GUI that drives Photoshop in the background to batch-normalize PSDs
against a reference file. Ships as a Windows `.exe` via PyInstaller; installer
via Inno Setup 6.

> v1.5.0+ is **Windows-only**. The Mac codepath was removed when the project
> pivoted to a team-tool (see `plan/2026-05-14-roadmap-6months-design.md`).

## Layout

```
app/
├── launcher.py              # Tkinter GUI entry point (two tabs + theme)
├── ps_driver.py             # Drives Photoshop via COM (pywin32)
├── updater.py               # NAS-based auto-update (v1.5.0+)
├── normalize_psd.jsx        # PSD Normalizer ExtendScript (bundled)
├── scripts/                 # Bundled .jsx scripts for Script Runner tab
├── assets/                  # Logo + .ico
├── requirements.txt         # Build deps
├── TA-F PSD DiffBatch.spec  # PyInstaller spec
├── build.bat                # One-click build (calls PyInstaller)
├── installer.iss            # Inno Setup script
├── version_info.txt         # .exe version metadata
└── README.md                # this file
```

## Run in dev mode

```powershell
cd app
python launcher.py
```

Requires: Python 3.10+, Photoshop installed locally, `pip install -r requirements.txt`.

## Build a distributable

```powershell
cd app
.\build.bat
```

Output: `dist\TA-F PSD DiffBatch\TA-F PSD DiffBatch.exe` (portable folder).

For the installer `.exe`: open `installer.iss` in Inno Setup 6 → Build → Compile
(F9). Output: `dist\installer\TA-F-PSD-DiffBatch-Setup-<version>.exe`.

## How it works

The GUI has two tabs sharing the same status bar, progress, and log output.

### Tab 1 — Normalizer

1. Pick **After** (reference) PSD, optional **Before** PSD, and a batch folder.
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

## Auto-update (v1.5.0+)

On startup the launcher polls `\\nas\TA-F\PS-BATCH\latest.json` (3s timeout,
silent fallback if unreachable). If a newer version is available the user
sees a non-modal dialog: **[Update] [Later] [Mute this version]**.

Mute persists per-version in `~/.tafpsd_presets.json`.

To publish an update:

1. Build a new installer (`build.bat` + Inno Setup).
2. Upload to `\\nas\TA-F\PS-BATCH\releases\PSDNormalizer-X.Y.Z-setup.exe`.
3. Update `\\nas\TA-F\PS-BATCH\latest.json` (see `app/updater.py` for schema).

## Distributing

The build is portable but the receiving machine must have:

- Windows 10/11 x64
- Photoshop installed (any reasonably modern version with ExtendScript / COM)
- No extra runtime (COM is built into the OS)
