# Changelog

All notable changes to TA-F PSD DiffBatch.

Format roughly follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Per-release CHANGELOGs from 1.2 onward also live at `releases/<ver>/CHANGELOG.md` —
those carry the full Chinese narrative; this top-level file is the short-form
index plus the **[Unreleased]** section under active development.

---

## [Unreleased]

Tracking 1.5.0 — the team-tool pivot. See
`plan/2026-05-19-v1.5-optimization-plan.md` for the full spec.

### Added
- **NAS-based auto-update** (`app/updater.py`). Startup probes
  `latest.json` in the team share with a hard 3 s deadline; download
  verifies SHA-256; install runs the Inno Setup `/SILENT` flow.
- **`Help` menu** in the appbar — `Onboarding (NAS)` / `About` /
  `Copy diagnostic info`.
- **Mute-per-version** for update prompts (`muted_versions` in
  `~/.tafpsd_presets.json`).
- **AppMutex** on Windows so Inno's `CloseApplications` can detect a
  running launcher during update install
  (`APP_MUTEX_NAME = "TA-F_PSD_DiffBatch_Mutex"`).
- **Structured logging** to `%LocalAppData%\TA-F\PS-BATCH\logs\app.log`
  (rotating 2 MB × 3). All modules log via `logging` — no more silent
  `print(stderr)` in the windowed `.exe`.
- **Diagnostic report** (`app/diagnostics.py`) bundles GUI log + app.log +
  `normalize_log.txt` + `script_run_log.txt`. Triggered from
  `Help → Copy diagnostic info`.
- **Atomic persistence write** + corrupt-file quarantine to
  `*.broken.<timestamp>.json`. Schema version stamping (`schema_version: 2`)
  with transparent v1 → v2 migration.
- **NAS configuration** externalized to `app/nas_config.json`
  (gitignored) with `nas_config.example.json` as the committed
  placeholder. `PSBATCH_UPDATE_URL` env var overrides both.
- **First-launch toast** when the NAS is unreachable; persists user mute
  via `muted_warnings`.
- **Version single source of truth** in `app/_version.py` —
  `version_info.txt` is rendered from `.tpl` by
  `tools/render_version.py`; Inno reads `GetEnv("APP_VERSION")` with
  `#error` fail-fast.
- **Build pipeline** rewritten as an 8-step `build.bat`
  (clean → deps → ruff → pytest → render → PyInstaller → ISCC →
  smoke). Pinned deps in `requirements.lock.txt`.
- **Smoke test** (`tools/smoke_test_exe.py`) launches the produced
  `.exe` for 3 s, fails the build if it can't stay alive.
- **Test suite** grown from 40 → 125 cases covering persistence,
  updater watchdog, ps_driver watchdog, nas_config, mutex consistency,
  build artifacts.

### Changed
- **PS COM call wrapped in a watchdog** — hung Photoshop no longer
  freezes the GUI; `_drive_ps` raises `TimeoutError` with actionable
  guidance ("close Photoshop manually and retry").
- **NAS manifest read on a daemon thread with hard deadline** — UNC
  reads can no longer stall startup past 3 s (was 5–10 s on a
  disconnected share).
- **PyInstaller `upx=False`** — trades ~15 % size for fewer SmartScreen
  / antivirus false positives.
- **Error dialogs go through `app/errors.py`** with a uniform `Title`,
  hint, and pointer to `app.log` + `Copy diagnostic info`.
- **About dialog** shows current auto-update source and Python /
  Photoshop versions.

### Removed
- Mac codepath. v1.5.0+ is **Windows-only**. The Mac `.app` build flow
  is gone from the release pipeline; the Python source still imports
  cleanly on macOS for dev work, but ships no artifact.

### Migration notes
- v1.4.x `~/.tafpsd_presets.json` upgrades transparently — `_load`
  detects pre-v2 files and stamps `schema_version: 2` on the next
  save. Corrupt files are renamed to `.broken.<ts>.json`; the app
  starts with empty state but the original bytes are preserved.
- The Windows mutex name **changed from `"TA-F PSD DiffBatch_Mutex"`
  to `"TA-F_PSD_DiffBatch_Mutex"`** (no spaces). During the first
  install of v1.5.0 over v1.4.x, Inno may not detect the running
  v1.4.x because the names differ. Close v1.4.x manually before
  installing v1.5.0 the first time.

---

## [1.4.1] — 2026-05-16

Patch release. Full notes: `releases/1.4.1/CHANGELOG.md`.

### Changed
- Fresh-install default appearance mode `Dark` → `System` (follows OS).
- `TA-F PSD DiffBatch.spec` excludes ML libs (torch / tensorflow /
  transformers / scipy / av / matplotlib / pandas / sympy / networkx) —
  `dist/` shrunk from ~2.3 GB to 72 MB.
- `installer.iss` temporarily drops the `chinesesimplified` language
  (community `.isl` not part of the default Inno install). Wizard runs
  in English; app UI itself stays bilingual.

---

## [1.4] — 2026-05-15

UI theme switcher + Windows build infrastructure. Full notes:
`releases/1.4/CHANGELOG.md`.

### Added
- **Three-way appearance switcher** (`Dark` / `Light` / `System`) in
  the appbar. Live-applies via CTk; persists to
  `~/.tafpsd_presets.json` (`appearance_mode`).
- **Light palette** mirror of the dark 1Password-style monochrome.
- **`app/build.bat`** one-click Windows build (lift from FILE-MANAGER
  pattern).
- **`app/version_info.txt`** — embedded `.exe` metadata.
- **`app/assets/AppIcon.ico`** — multi-resolution icon from logo.png.
- **`installer.iss`** improvements: `OutputDir=dist\installer\`,
  `SetupIconFile`.

### Changed
- Palette refactor: `M["x"]` → `C("x")` returning `(light, dark)`
  tuple, 126 call-sites updated. Theme switch uses CTk's native dual
  mechanism — no per-widget reconfigure.
- `tk.PanedWindow` reconfigured manually in `_on_theme_change` (no CTk
  tuple support).

### Deferred to v1.5
- Original v1.4 plan ("RUN BATCH structural transform + auto mask")
  pushed out — see `plan/2026-05-14-roadmap-6months-design.md`.

---

## [1.3] — 2026-05-14

Script Runner Tab + queue. Full notes: `releases/1.3/CHANGELOG.md`.

### Added
- **Tab 2 — Script Runner**: run any user `.jsx` against every PSD in
  a folder. Sources include bundled `app/scripts/` + user-added dirs
  (persisted via `+ Dir`). One-off `.jsx` via Browse.
- **Multi-script queue** (`+ Add` / `×` / `Clear`) — each script is
  its own pass over the batch folder. Progress bar compositional:
  `(scripts_done + current_internal) / queue_total`.
- **Output mode** for Script Runner: `Save to output` / `Overwrite` /
  `Don't save`. Per-PSD error isolation — single failure logged, batch
  continues.
- **Built-in `app/scripts/_example_flatten.jsx`** demonstrating the
  "only touch `app.activeDocument`, don't `save()` / `close()`"
  contract.

### Changed
- `load_presets` / `save_presets` factored into `_load_userdata` /
  `_save_userdata`. Preset file shape:
  `{"presets": [...], "user_scripts_dirs": [...]}`.
- `ps_driver.run_custom_script(...)` added; reuses `_drive_ps` /
  `_tail_log` / `_watch_cancel` / `_to_jsx_string`.
- `_handle_done` understands the queue result shape.

---

## [1.2] — 2026-05-12

Cancel + preset polish. Full notes: `releases/1.2/CHANGELOG.md`.

### Added
- **CANCEL button** for RUN BATCH; `Cmd-.` / `Ctrl-.` shortcut.
  Cancels at PSD boundaries via a `.cancel` marker file the ExtendScript
  side checks each iteration.
- **Preset delete + UNDO toast** (8 s) replacing the previous confirm
  dialog.
- **Multi-path DnD detection** — drop multiple paths on a field, the
  first wins; rest logged.

### Changed
- `load_presets` / `save_presets` failures now log to stderr (was
  silent).
- `normalize_psd.jsx` default reference path moved into the project
  layout under `Projects/TA-F/PS-BATCH/reserach/psd/`.
- `ps_driver.run_batch` accepts `cancel_event: threading.Event`.

### Removed
- Orphaned `_run_single.jsx` (unreferenced, stale paths).
- Preset delete confirm dialog (UNDO flow replaces it).

---

## [1.1] — 2026-05-11

Mac `.app` build + minor UI polish. (No standalone CHANGELOG — see
`releases/1.1/source/`.)

### Added
- Mac `.app` build via PyInstaller produced and archived in
  `releases/1.1/`.

### Changed
- Initial polish on field layouts + reveal-output button.

---

## [1.0] — 2026-05-11

Initial release. (No CHANGELOG — see `releases/1.0/source/README.md`.)

### Added
- Cross-platform Tkinter GUI launcher (`app/launcher.py`).
- Photoshop driver via `osascript` on Mac and COM (`win32com`) on
  Windows (`app/ps_driver.py`).
- ExtendScript brain (`app/normalize_psd.jsx`) reading recipe from
  After PSD, diffing against Before PSD, applying batch normalize to
  a folder.
- PyInstaller spec + setup.py + Mac `.app` archived.
