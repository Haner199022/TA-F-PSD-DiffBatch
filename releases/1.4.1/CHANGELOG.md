# 1.4.1 — 2026-05-16

Patch release. 把全新安装时的默认 appearance mode 从 `Dark` 改为 `System`（跟随系统）。

## Changed

- `launcher.py:171` — `_load_saved_appearance_mode()` 在 preset 文件不存在或没有 `appearance_mode` 键时，fallback 从 `"Dark"` 改为 `"System"`。
  - 影响：v1.4.1 全新安装用户首次启动会跟随系统主题；已经用过 v1.4.0 的用户不受影响（他们的 preset 文件里已经写了选择）。
  - 决策原因：现代桌面应用默认跟随系统更符合用户预期。

## Build

- 沿用 1.4.0 的 Windows 构建链路：`build.bat` + Inno Setup `installer.iss`
- 输出：`TA-F-PSD-DiffBatch-Setup-1.4.1.exe`（23.7 MB，lzma2 压缩）
- 构建环境改进：
  - `TA-F PSD DiffBatch.spec` 加 `excludes=[torch, tensorflow, transformers, scipy, av, ...]`，避免 PyInstaller 把系统 Python 里的 ML 库（2+ GB）误打包。dist 体积从 2.3 GB → 72 MB。
  - `installer.iss` 暂时移除 `chinesesimplified` 语言（默认 Inno Setup 6 安装不带 `ChineseSimplified.isl`，需要手动从社区下载）。安装向导现以英文运行；应用本身仍为中文 UI。

## 升级路径

- 已装 1.4.0 的同事：覆盖安装即可，preset 文件保留
- 全新安装：默认主题 = System（跟随系统）
