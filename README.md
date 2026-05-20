# TA-F PSD DiffBatch

[![latest release](https://img.shields.io/github/v/release/Haner199022/TA-F-PSD-DiffBatch?include_prereleases&label=release)](https://github.com/Haner199022/TA-F-PSD-DiffBatch/releases)
[![v1.5.0 milestone](https://img.shields.io/github/milestones/progress-percent/Haner199022/TA-F-PSD-DiffBatch/1?label=v1.5.0%20progress)](https://github.com/Haner199022/TA-F-PSD-DiffBatch/milestone/1)
[![open issues](https://img.shields.io/github/issues/Haner199022/TA-F-PSD-DiffBatch)](https://github.com/Haner199022/TA-F-PSD-DiffBatch/issues)
[![last commit](https://img.shields.io/github/last-commit/Haner199022/TA-F-PSD-DiffBatch/main)](https://github.com/Haner199022/TA-F-PSD-DiffBatch/commits/main)

[![python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/windows/)
[![platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)](#install-for-colleagues)
[![tests](https://img.shields.io/badge/tests-125%20passed%2C%201%20skipped-brightgreen)](app/tests/)
[![status](https://img.shields.io/badge/status-pre--release-orange)](plan/2026-05-19-rc-1.5.0.md)

> Tkinter GUI that drives Photoshop in the background to batch-normalize
> PSDs against a reference file. Windows team tool with NAS-based
> auto-update — ships to ~5 colleagues; not a public-distribution
> product.

## What it does

Point it at:

- an **After PSD** (the reference / target appearance)
- a **Batch folder** of PSDs to normalize against it

Click **RUN BATCH**. The tool drives Photoshop via COM, applies the
After file's recipe (layer ordering, filters, smart-object structure)
to every PSD in the folder, and writes results to a sibling
`_normalized/` directory. Originals untouched.

Tab 2 — **Script Runner** — runs any user `.jsx` over the same batch
folder. Supports multi-script queues.

## Status

**v1.5.0** is in **pre-release**. See
[`plan/2026-05-19-rc-1.5.0.md`](plan/2026-05-19-rc-1.5.0.md) for the
acceptance checklist. Production releases are tracked in
[Releases](https://github.com/Haner199022/TA-F-PSD-DiffBatch/releases).

## Install (for colleagues)

1. Grab the latest installer:
   - **GitHub Releases** → [latest](https://github.com/Haner199022/TA-F-PSD-DiffBatch/releases/latest),
     download `TA-F-PSD-DiffBatch-Setup-X.Y.Z.exe`, **or**
   - **NAS** → `\\nas\TA-F\PS-BATCH\releases\` (faster if you're
     on the office network)
2. Double-click the installer. If Windows SmartScreen blocks it:
   `More info` → `Run anyway`. See
   [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) §SmartScreen for context.
3. Launch from Start menu. The tool auto-checks for updates on every
   launch — silent if you're offline, dialog if a newer version is on
   NAS.

## Build from source (for maintainer)

```powershell
# Windows 10/11 x64; Python 3.10+; Inno Setup 6
cd app
python -m pip install -r requirements.lock.txt
.\build.bat
```

8-step pipeline runs clean → deps → ruff → pytest → render version →
PyInstaller → ISCC → smoke test. Output:

- `app\dist\TA-F PSD DiffBatch\` — portable folder build
- `app\dist\installer\TA-F-PSD-DiffBatch-Setup-X.Y.Z.exe` — installer

See [`NAS-LAYOUT.md`](NAS-LAYOUT.md) §"Release SOP" for the full
release procedure (build → upload to NAS → update `latest.json`).

## Documentation

| Doc | What's in it |
|---|---|
| [`CHANGELOG.md`](CHANGELOG.md) | What changed in each version (Keep-a-Changelog format) |
| [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) | 7 most common issues + how to fix |
| [`NAS-LAYOUT.md`](NAS-LAYOUT.md) | NAS share layout + `latest.json` schema + release SOP |
| [`plan/`](plan/) | Design docs — optimization plan, roadmap, RC checklist |
| [`app/README.md`](app/README.md) | App-internal architecture notes |

## Contributing (for alpha colleagues)

This is an internal team tool. Feedback channels:

- 🐛 [Open a bug report](https://github.com/Haner199022/TA-F-PSD-DiffBatch/issues/new?template=bug_report.yml) — has a paste-here field for the diagnostic info `Help → Copy diagnostic info` produces
- 💡 [Suggest a feature](https://github.com/Haner199022/TA-F-PSD-DiffBatch/issues/new?template=feature_request.yml) — problem-first, please
- 💬 [Ask in Discussions Q&A](https://github.com/Haner199022/TA-F-PSD-DiffBatch/discussions/categories/q-a) — for "is this a bug?" type questions
- 📢 [Watch Announcements](https://github.com/Haner199022/TA-F-PSD-DiffBatch/discussions/categories/announcements) — release news

The fastest path is always **in the app: `Help → Copy diagnostic info`
→ paste to maintainer chat**. The GitHub routes are for when you want
something tracked.

## License

No open-source license attached — this is an internal team tool, all
rights reserved by the maintainer. If you want to use the code outside
the team, contact the maintainer first.
