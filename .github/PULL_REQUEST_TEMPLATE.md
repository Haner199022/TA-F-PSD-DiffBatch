<!--
Lean PR template — keep boxes that apply, delete the rest. The "if you
touched X, do Y" checklist exists because each item caught a real bug
during v1.5.0 development; reading it costs less than re-introducing
those bugs.
-->

## Summary

<!-- One paragraph. What + why. Skip the "how" — diff already shows that. -->

## Changes

- 

## Verification

- [ ] `cd app && python3 -m pytest tests/ -q` stays green (baseline: **125 passed, 1 skipped**)
- [ ] `python3 -m py_compile` clean on edited `.py`
- [ ] No new `print(file=sys.stderr)` — production exe is `console=False`; use `log = logging.getLogger(__name__)`
- [ ] No new `except Exception: pass` without a `log.debug/warning/error` line explaining the intent
- [ ] **If you touched `app/_version.py`**: ran `python3 tools/render_version.py` so `version_info.txt` matches
- [ ] **If you touched `app/installer.iss` `MutexName` or `launcher.APP_MUTEX_NAME`**: both still equal (test enforces)
- [ ] **If you touched `app/persistence.py`** schema: `SCHEMA_VERSION` bumped + `_migrate()` step added
- [ ] **If you touched `app/launcher.py`**: REGION banners still align with content (no stale "future split target" notes)
- [ ] **UI changes**: ran manual smoke against [`plan/2026-05-19-rc-1.5.0.md`](../plan/2026-05-19-rc-1.5.0.md) §15-item checklist (note which items)

## Related

- Plan / decision: <!-- link to `plan/...` file or `D-N` from the decision board -->
- Closes: <!-- #N if applicable -->

## CHANGELOG

- [ ] Updated `[Unreleased]` block in [`CHANGELOG.md`](../CHANGELOG.md) — or note **N/A** here for trivial / internal-only changes.

## Migration notes for users

<!--
REQUIRED whenever this PR touches:
  - persistence schema       (existing presets may break)
  - installer.iss flags      (installer behavior changes)
  - AppMutex name            (upgrade detection breaks)
  - NAS layout / nas_config  (auto-update breaks)
  - _version.py              (downstream metadata)

Otherwise write "None."
-->

None.
