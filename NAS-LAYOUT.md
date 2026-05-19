# NAS Layout & Release SOP

Authoritative spec for the team share that powers v1.5.0+ auto-update.
If you're an alpha colleague trying to use the tool, skip ahead to
[Onboarding](#onboarding-for-colleagues); if you're the maintainer cutting
a release, [Release SOP](#release-sop) is the part you want.

---

## Share layout

```
\\nas\TA-F\PS-BATCH\
├── latest.json                ← Auto-update manifest (read on startup)
├── README.md                  ← Onboarding doc (Help → Onboarding opens this)
├── releases\                  ← All shipped installers
│   ├── TA-F-PSD-DiffBatch-Setup-1.5.0.exe
│   ├── TA-F-PSD-DiffBatch-Setup-1.4.1.exe
│   └── TA-F-PSD-DiffBatch-Setup-1.4.0.exe
│                              ← Keep the latest 3 for rollback (see §Rollback)
└── team_scripts\              ← v1.5.1+ shared Script Runner library (empty for 1.5.0)
```

- `\\nas\` is a placeholder. Replace with the team's actual share
  (e.g. `\\fileserver01\TA-F\PS-BATCH\`). The build that ships to
  colleagues bakes the real path in via `app/nas_config.json`
  ([§ Build-machine setup](#build-machine-setup) below).
- Read access required for everyone; write access only for the
  release maintainer.

---

## `latest.json` schema

```json
{
  "version":     "1.5.0",
  "exe_url":     "\\\\nas\\TA-F\\PS-BATCH\\releases\\TA-F-PSD-DiffBatch-Setup-1.5.0.exe",
  "exe_sha256":  "<lowercase hex, 64 chars>",
  "changelog":   "Auto-update infrastructure landed.\n- New Help menu\n- ...",
  "mandatory":   false
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `version` | string | yes | Semver; **must** start with digits. Garbage strings are ignored at compare time, never appear "newer". |
| `exe_url` | string | yes | Absolute UNC path **or** `http(s)://` URL. Both work; UNC is preferred for in-office speed. |
| `exe_sha256` | string | yes | Lowercase hex digest of the installer at `exe_url`. The launcher computes SHA-256 of the downloaded file and refuses to apply on mismatch. |
| `changelog` | string | no | Multi-line OK. Shown verbatim in the in-app update dialog's scrollable text box. |
| `mandatory` | bool | no | If `true`, the update dialog hides the `LATER` and `MUTE` buttons. Use sparingly — reserved for security fixes. |

Default values when fields are missing: `changelog=""`, `mandatory=false`.

---

## Release SOP

The full pipeline is wrapped in `app/build.bat`. The maintainer's job is
~5 minutes of file-shuffling on top.

### One-time build-machine setup

1. Install **Python 3.10+** (tick "Add to PATH" during install).
2. Install **Inno Setup 6** from <https://jrsoftware.org/isdl.php>.
3. Clone the repo, then **create `app/nas_config.json`** (gitignored):
   ```json
   {
     "nas_root":      "\\\\fileserver01\\TA-F\\PS-BATCH",
     "manifest_name": "latest.json"
   }
   ```
   Replace `fileserver01` with the real share. This file gets baked
   into the shipped `.exe` so colleagues don't need to configure
   anything.
4. (Optional, one time) `pip install -r app/requirements.lock.txt`
   so `build.bat` step [2/8] has nothing to download.

### Per-release steps

1. **Update version**:
   ```diff
   - __version__ = "1.5.0"
   + __version__ = "1.5.1"
   ```
   Edit `app/_version.py` only — `version_info.txt` and Inno's
   `AppVersion` derive from this.

2. **Update CHANGELOG.md**: move `[Unreleased]` content into a new
   `[1.5.1] — YYYY-MM-DD` section; start a fresh `[Unreleased]` if
   useful.

3. **Build**:
   ```
   cd app
   build.bat
   ```
   8 steps run in order; any failure aborts. Final output:
   `app\dist\installer\TA-F-PSD-DiffBatch-Setup-1.5.1.exe`.

4. **Compute SHA-256**:
   ```powershell
   Get-FileHash dist\installer\TA-F-PSD-DiffBatch-Setup-1.5.1.exe -Algorithm SHA256
   ```

5. **Upload to NAS**:
   ```powershell
   copy dist\installer\TA-F-PSD-DiffBatch-Setup-1.5.1.exe \\nas\TA-F\PS-BATCH\releases\
   ```

6. **Update `latest.json` on NAS** — edit the file in place. Bump
   `version`, point `exe_url` to the new file, paste the SHA-256,
   write a changelog blurb. Keep file UTF-8, no BOM.

7. **Smoke on a colleague's machine (or a clean VM)**:
   - Old version's auto-update dialog should pop within ~5 s of
     launch.
   - Click `UPDATE` — installer runs silently, app restarts, About
     dialog shows new version.

8. **Announce** in the team chat. Include the changelog blurb and
   the SHA-256 (so paranoid colleagues can verify out-of-band).

### Rollback

If a release turns out broken **after** colleagues have it:

1. **Don't delete the bad installer** — colleagues already pinned it
   in `muted_versions` if they used `MUTE`; leave it as evidence.
2. In `latest.json`, set `version` back to the previous good version
   and point `exe_url` at the matching installer in
   `releases\`. Set `mandatory: true` so colleagues with the bad
   build see no `LATER` button.
3. Next launcher start, every machine pulls the downgrade silently.
4. After everyone's downgraded, you can keep `mandatory: true` or
   flip back to `false` — bookkeeping only.

Because the auto-update flow uses semver comparison, "downgrading" by
manifest works exactly like upgrading; the launcher treats a higher
number in `latest.json` as the canonical target regardless of direction.

### Why keep three installers

- `releases\` holds the current + previous 2. Anything older can be
  archived to a cold folder.
- Rollback to N-1 is one `latest.json` edit. Rollback further
  requires fishing the file out of cold storage.

---

## Onboarding for colleagues

If you're using PS-BATCH for the first time:

1. **First install**: ask the maintainer for the installer link or
   pick it up from `\\nas\TA-F\PS-BATCH\releases\` directly. Run the
   `.exe`, click Next.
2. **After that, updates are automatic**. On startup the tool quietly
   checks for a new version on the NAS; if there is one you see a
   dialog with three buttons:
   - `UPDATE` — downloads + replaces + restarts automatically (~10 s).
   - `LATER` — next launch will ask again.
   - `MUTE THIS VERSION` — never ask again for this specific version.
     A future version will still notify you.
3. **If the share is unreachable** (off the office network, VPN
   down), the tool just runs the local version. You'll see a one-off
   toast on first launch saying so; click `不再提醒` to silence it.
4. **Stuck?** `Help → Copy diagnostic info` copies a paste-ready
   report (version + paths + logs from three sources) to your
   clipboard. Paste into chat to the maintainer.

See `TROUBLESHOOTING.md` for known issues + workarounds.

---

## File lifecycle

| Object | Source of truth | Edited by | When |
|---|---|---|---|
| `latest.json` | NAS | Release maintainer | Every release |
| Installer `.exe` | NAS `releases\` | Release maintainer | Every release |
| `README.md` on NAS | NAS | Release maintainer | When colleague onboarding changes |
| `app/nas_config.json` | Build machine | Maintainer once | One-time setup; updated only if NAS path moves |
| `app/_version.py` | Repo | Release maintainer | Every release (single edit per bump) |
| `CHANGELOG.md` | Repo | Release maintainer | Every release |
