# 1.3 — 2026-05-14

第二个大功能版本：Script Runner Tab。在原 PSD Normalizer 之外加了一个通用入口，可以跑任意用户 `.jsx` 脚本，并支持多脚本队列串跑。

> 注：v1.3 的实际内容与 1.2 CHANGELOG 里预告的「structural transform + auto mask」不同。原计划的 RUN BATCH 结构变换升级未在本版本实施，移到 v1.4 规划。

## Added

### Script Runner Tab（新增功能）
- **CTkTabview 双 Tab 布局**：Tab 1 "Normalizer"（原全部功能）+ Tab 2 "Script Runner"（新）。
- **脚本选择**：下拉自动列出 `app/scripts/`（PyInstaller 打包内置）+ 用户自定义目录（preset 记忆）。**Browse** 可一次性选任意 `.jsx`。
- **+ Dir 按钮**：添加用户脚本目录，写入 `~/.tafpsd_presets.json` 的 `user_scripts_dirs`，跨启动持久。
- **Output mode 三选一**：
  - *Save to output*（默认）— 保存副本到 `<batch>/../_script_out/` 或用户指定目录
  - *Overwrite* — `save()` 覆盖源 PSD
  - *Don't save* — 关闭不保存（适合脚本自己导出 PNG/JPG）
- **错误隔离**：单个 PSD 失败仅记日志，整批继续。

### 多脚本队列
- **+ Add 按钮**：把当前下拉选中的脚本加入运行队列。
- **CTkScrollableFrame 队列列表**：显示 `1. xxx ×` / `2. yyy ×`，单行 × 删除，**Clear** 全清。
- **执行语义**：每个队列项作为独立一轮 batch（A 跑完所有 PSD，再 B 跑所有 PSD），不在 PS 里链式打开。
- **进度合成**：队列模式下进度条按 `(已完成轮数 + 当前轮内进度) / 总轮数` 加权，状态条显示 `Script i/n · k/m — file.psd`。
- **单脚本回退**：队列空 + 下拉有选时，RUN SCRIPT 走单脚本流程（向后兼容）。
- **聚合结果**：跑完汇总每个脚本的 ok/failed 计数；errors 列表附 `script` 字段标明来源。

### 内置 + 打包
- 新增 `app/scripts/` 内置目录 + 示例脚本 `_example_flatten.jsx`，演示「只操作 activeDocument，不要自己 save/close」契约。
- 两份 `.spec`（`PSD Normalizer.spec` + `TA-F PSD DiffBatch.spec`）的 `datas` 加 `('scripts', 'scripts')`，PyInstaller 把脚本一起带上。Inno Setup `recursesubdirs` 自动跟进。

## Changed
- `load_presets / save_presets` 重构为 `_load_userdata / _save_userdata` 底层，preset 文件结构变为 `{"presets": [...], "user_scripts_dirs": [...]}`，向后兼容旧只有 `presets` 的格式。
- `ps_driver.py` 加 `run_custom_script(script_path, batch_folder, output_mode, ...)`：生成 wrapper jsx，遍历 PSD → open → evalFile → 按 mode 保存/关闭。复用 `_drive_ps` / `_tail_log` / `_watch_cancel` / `_to_jsx_string`。
- `_handle_done` 支持新 result 形状（`{queue, scripts, processed, failed, errors, outputFolder}`）。
- `_maybe_update_progress` 在 `self._queue_total > 1` 时走合成公式；单脚本模式保持原行为。
- `installer.iss` `AppVersion` 1.1 → 1.3。

## Removed
- 无。

## Build
- 本版本 Mac `.app` 已 build 并归档到 `releases/1.3/mac/`（PyInstaller 6.20 + Python 3.12）。
- Windows `.exe` 待 Windows 机器上跑同样的 spec 后产出（`installer.iss` 已就位）。

## 已知约束 / 提示
- 队列在「链式输出」语义上的陷阱：默认 Save to output 模式下，第二个脚本跑的还是源 PSD 而不是第一个脚本的输出（因为 PS 中间关闭了文档）。想让 B 接 A 的结果 → 改 Output mode 为 **Overwrite**。
- 用户脚本不要自己调 `save()` / `close()`，wrapper 统一处理。详见 `app/scripts/_example_flatten.jsx`。
- 取消粒度仍是 PSD 边界（队列中也包括脚本边界），点 CANCEL 后会在当前 PSD 跑完时停。
