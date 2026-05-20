# Troubleshooting

Known issues and the fastest way out of each. Roughly ordered by how
often the maintainer expects to field the question.

> **First step for any problem**: `Help → Copy diagnostic info` →
> paste into chat. The report includes version, paths, GUI log,
> `app.log`, and the latest `normalize_log.txt` / `script_run_log.txt`.
> Most issues are diagnosable from that alone.

---

## SmartScreen / Defender blocks the installer

**Symptom**: Double-clicking the installer shows
"Windows protected your PC" or the file is deleted on download.

**Why**: The installer isn't code-signed (we don't run an EV
certificate — see `plan/.../v1.5-optimization-plan.md §15`). UPX
compression was disabled in v1.5.0 to reduce false-positive rate, but
SmartScreen still cold-starts cautiously on unfamiliar binaries.

**Fix**:
1. On the SmartScreen dialog, click **More info** → **Run anyway**.
2. If Defender deletes the file outright before you can click it,
   add the installer's folder (e.g. `Downloads\`) to Defender
   exclusions for the install session, then re-download.
3. Once installed once, subsequent updates run silently via Inno
   Setup `/SILENT` and don't re-trigger SmartScreen.

---

## Auto-update dialog never appears

**Symptom**: You launch the tool and don't see the
"UPDATE AVAILABLE" dialog you expected.

**Likely causes** (in order of probability):

### 1. NAS unreachable
- Look for the bottom-of-window toast on first launch:
  "自动更新源不可达 (\\nas\\…). 可继续使用本地版本…"
- Most often: off the office network or VPN down.
- Check: open File Explorer → paste `\\nas\TA-F\PS-BATCH\` →
  does the share open?

### 2. Already on the latest version
- `Help → About` shows the current version. Cross-check with
  `\\nas\TA-F\PS-BATCH\latest.json` (`version` field).

### 3. You muted this version
- `~\.tafpsd_presets.json` → look for the version in `muted_versions`.
  Edit the file (in any text editor, no app close needed) and remove
  the entry to re-enable the prompt for that version.

### 4. Manifest malformed
- Read `app.log`
  (`%LocalAppData%\TA-F\PS-BATCH\logs\app.log`) — look for
  `manifest unreachable` or `manifest malformed` lines.
- This one's on the release maintainer; ping them with the diagnostic.

---

## Auto-update download fails

**Symptom**: Click `UPDATE` in the dialog → progress bar starts →
error dialog "Update failed".

**Why**: One of:
- NAS connection dropped mid-download.
- SHA-256 mismatch (the installer on NAS was replaced or corrupt).
- Local disk full or `%TEMP%` write blocked.

**Fix**:
1. **Manual install fallback** — `\\nas\TA-F\PS-BATCH\releases\` has
   the same installers the auto-update flow uses. Open the share,
   double-click the version you want.
2. If `app.log` mentions "checksum mismatch", contact the
   maintainer — the NAS file is genuinely wrong. Don't re-download
   in a loop; that won't help.

---

## Photoshop seems frozen during RUN BATCH

**Symptom**: Progress bar stops moving; CANCEL no longer responds
within ~30 s.

**Why**: PS itself hung. v1.5.0 added a watchdog so the GUI itself
stays responsive, but PS still needs to be killed manually.

**Fix**:
1. **Click CANCEL anyway** — it sets the cancel flag, which PS picks
   up at the next PSD boundary. If PS is alive but slow, this works.
2. If 30 s later still stuck → **open Task Manager, end
   `Photoshop.exe`**. The tool will then surface a `TimeoutError`
   with a message saying "close Photoshop manually and retry".
3. Reopen Photoshop, click `RUN BATCH` again. The cancel marker
   from the dead run is cleaned up automatically.

The watchdog timeout is **30 minutes** for a full batch. If your
batches run longer than that, the value can be changed in
`app/ps_driver.py` (`_drive_ps(timeout_secs=...)`). The plan tracks
this as decision D14 for adjusting from About in a future version.

---

## Presets vanished after upgrade

**Symptom**: After updating to v1.5.0+, the Presets dialog is empty;
saved After/Before recipes are gone.

**Likely cause**: A previous app shutdown crashed mid-write and left
`~/.tafpsd_presets.json` corrupt. v1.5.0's `_load` detects this and
moves the bad file aside.

**Fix**:
1. Open `~/` in File Explorer (or `%USERPROFILE%`).
2. Look for `.tafpsd_presets.broken.YYYYMMDD_HHMMSS.json`.
3. Open it — if the JSON is partially intact, copy your presets
   array into the live `.tafpsd_presets.json`. Restart the tool.
4. If the broken file is truly garbage, your history is gone. v1.5.0
   prevents this happening again (atomic writes via `os.replace`).

---

## "Couldn't reach NAS share" when clicking Help → Onboarding

**Symptom**: `Help → Open Onboarding (NAS)` shows a messagebox
"Couldn't reach the NAS share at: \\nas\\..."

**Fix**: Same root cause as "NAS unreachable" above — not on
network, or share isn't mounted. Connect to the office network /
VPN, then try again. The onboarding README lives at
`\\nas\TA-F\PS-BATCH\README.md`; if you have local access you can
also navigate there in File Explorer directly.

---

## I changed my mind — un-mute a warning or version

**Mute scope** | **Stored as** | **How to clear** |
|---|---|---|
| "Don't ask me about v1.5.1 again" | `muted_versions: ["1.5.1"]` in `~/.tafpsd_presets.json` | Edit file, remove entry, save. App can be open or closed. |
| "Don't show the NAS-unreachable toast" | `muted_warnings: ["nas_unreachable"]` (same file) | Same. |
| All preferences at once (nuclear) | The whole `.tafpsd_presets.json` | Delete the file. Restart. App starts with defaults. |

---

## I want to run from source instead of the installer

```powershell
cd app
python -m pip install -r requirements.lock.txt
python launcher.py
```

Requires Python 3.10+, Photoshop installed locally, and (on Windows)
the auto-update flow needs `pywin32` — included in
`requirements.lock.txt` via a `sys_platform` marker.

In dev mode, the AppMutex isn't acquired (pywin32 may be missing on
Mac dev), so the Inno auto-relaunch flow can't be exercised. Update
prompts still appear; clicking `UPDATE` will fail visibly because the
installer can't replace a running Python interpreter.

---

## Reporting a new bug

Three paths, in order of speed:

1. **In-app** (fastest for you) — `Help → Copy diagnostic info` →
   paste into chat to the maintainer.
2. **GitHub issue** (best for tracking) — open a [Bug
   report](https://github.com/Haner199022/TA-F-PSD-DiffBatch/issues/new?template=bug_report.yml).
   The form has a dedicated paste-here field for diagnostic info.
3. **GitHub Discussions** (best for "is this a bug?") — if you're
   not sure whether what you're seeing is a real bug or just
   misunderstanding, ask in
   [Discussions Q&A](https://github.com/Haner199022/TA-F-PSD-DiffBatch/discussions/categories/q-a)
   first. The maintainer (or another colleague who hit it) can
   confirm before you spend time writing a full bug report.

For paths 2-3, include:
- Output of `Help → About` (version + Python + PS).
- Last 200 lines of `%LocalAppData%\TA-F\PS-BATCH\logs\app.log`.
- What you did + what you expected + what happened.

The diagnostic blob from path 1 covers all three automatically;
prefer pasting it.
