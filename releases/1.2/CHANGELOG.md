# 1.2 — 2026-05-12

Source snapshot before the v1.3 feature expansion (structural transform + auto mask).

## Added
- **Cancel button** for RUN BATCH. Cmd-. / Ctrl-. shortcut. Cancellation works at PSD boundaries via a `.cancel` marker file in the output folder.
- **Preset delete undo** — toast banner with UNDO button (8s) replaces the previous confirm dialog. Toast survives closing the Presets dialog.
- **Multi-path DnD detection** — when user drops multiple paths on a field, stderr logs `[dnd] multi-path drop detected, using first: ...`.
- **`_register_drop_target` helper** — centralizes the `customtkinter._entry` private-attribute access for tkinterdnd2 registration.

## Changed
- `load_presets` / `save_presets` failures now log to stderr instead of silently passing.
- `normalize_psd.jsx` `DEFAULT_REFERENCE_PATH` updated from old `Projects/ps批量处理/` location to new `Projects/TA-F/PS-BATCH/reserach/psd/H26_SET_01_SASS_&_SUNSHINE_INTL_PACKSHOT_RGB_after.psd`.
- `ps_driver.run_batch` accepts optional `cancel_event: threading.Event` parameter.
- `import sys` moved from mid-file to top imports section.

## Removed
- Orphaned `_run_single.jsx` from project root (was unreferenced + had stale hardcoded paths).
- Preset deletion confirm dialog (replaced by delete + undo flow).

## Build
- Source files only; no rebuilt `.app` archived here. Build is the same PyInstaller flow as 1.1 (see `app/PSD Normalizer.spec` + `app/installer.iss`).
