# 1.4 — 2026-05-15

UI 主题切换版本。原 v1.4 规划的 RUN BATCH 结构变换升级未实施，移到 v1.5 规划。

## Added

### 明暗主题三档切换
- **appbar 右侧 SegmentedButton**：三档 `Dark / Light / System`，点一下立刻切换（无需重启）。
- **跟随系统**（System 模式）：使用 CTk 的 `darkdetect` 自动跟随 macOS / Windows 系统主题。
- **持久化**：选择写入 `~/.tafpsd_presets.json` 的 `appearance_mode` 键，下次启动自动应用。
- **浅色配色**（纯白底 + 黑字 + 黑按钮 + 加深的状态色）与原深色配色镜像对称，保持 1Password 单色风格。

## Changed
- 配色 palette 重构：`M` 字典拆为 `M_DARK` + `M_LIGHT`，加 `C(key)` helper 返回 `(light, dark)` 元组。
- 全文 126 处 `M["x"]` 调用替换为 `C("x")`，利用 CTk 双值传参原生机制实现热切换（无需遍历重 configure widget）。
- `tk.PanedWindow`（不支持 CTk 元组）在 `_on_theme_change` 中手工 reconfigure `bg`。
- 启动时 `ctk.set_appearance_mode()` 从硬编码 `"dark"` 改为读取 preset 文件。
- `installer.iss` `AppVersion` 1.3 → 1.4。

## Removed
- 无。

## Build

### Mac
- Mac `.app` 已 build 并归档到 `releases/1.4/mac/`（PyInstaller 6.20 + Python 3.12）。

### Windows 构建基础设施补强（借鉴 FILE-MANAGER 项目）
- 新增 `app/build.bat` — Windows 一键 build 脚本：自动检查 Python / 清理 / pip install / pyinstaller / 验证 / 友好下一步提示。Win 用户**双击即可**，不用手敲命令。
- 新增 `app/version_info.txt` — PyInstaller 嵌入 Win .exe 元信息（CompanyName=TA-F, FileVersion=1.4.0, ProductName=TA-F PSD DiffBatch, FileDescription, OriginalFilename）。.exe 右键属性"详细信息"显示。
- 新增 `app/assets/AppIcon.ico` — 从 `assets/logo.png` 用 Pillow 生成多分辨率 ICO（16/32/48/64/128/256），透明填充保持比例。Win .exe 不再使用默认 Tk 图标。
- 更新 `TA-F PSD DiffBatch.spec`：EXE 段加 `icon=icon_path` + `version=version_file`，平台条件判断（Win 用 .ico + version_info，Mac 自动跳过）。
- 更新 `installer.iss`：`OutputDir` 从 `installer_output` 改为 `dist\installer`（所有 build 产物集中到 `dist\`，一次 `rmdir dist` 全清）；加 `SetupIconFile=assets\AppIcon.ico`。
- Win buildkit zip `releases/1.4/TA-F-PSD-DiffBatch-1.4-win-buildkit.zip` 已含新增的所有构建文件。
- 配套 `WINDOWS-BUILD.md` 简化到 2 步主流程（拷贝 + 双击 build.bat），其他作为可选展开。

## 已知约束
- **macOS 系统主题实时跟随**：CTk 通过 `darkdetect` 库轮询系统设置，理论上能实时跟随；最差情况是启动时确定，运行中需手切。
- **PanedWindow 切换粒度**：手工 reconfigure，无故障兼容；CTkSegmentedButton 的"激活档"视觉反馈在浅色下是黑按钮 + 白字，深色下是白按钮 + 黑字，对比度都足够。
- **状态色（ok/danger/warn）在浅色下用了加深版本**（#16A34A / #DC2626 / #D97706），优先可读性而非鲜艳度。

## 下一版（v1.5）规划
- 原 v1.4 计划的 RUN BATCH 结构变换升级（智能图层匹配 + 自动 smart object + 自动蒙版 + filter chain 重放）顺延到 v1.5。详见 memory `project_ta-f_ps-batch.md`。
