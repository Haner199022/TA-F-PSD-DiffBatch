---
title: PS-BATCH · Script Runner Tab 实施计划
status: in-progress
created: 2026-05-12
---

# Script Runner Tab — 让 PS-BATCH 能跑用户自定义 .jsx

## 目标
在现有 PSD Normalizer 之外，增加一个通用入口：用户选一个 `.jsx` 脚本 + 一个 PSD 文件夹，对文件夹里每个 PSD 跑一次该脚本。

## 设计决策
- **用户脚本零约定**：wrapper 负责 `app.open(File(psd))` 和保存/关闭，用户脚本只对 `activeDocument` 操作即可。网上抓的 jsx 多数能直接用。
- **默认 Output mode = "另存到 output 文件夹"**：原 PSD 不被改写。可在 GUI 切到「原地覆盖」或「不保存」。
- **错误隔离**：单个 PSD 失败仅写日志，整批继续。
- **UI 入口 = Tab 2**：现有界面整体收进 Tab 1，不改逻辑。

## 改动清单

### 1. `app/ps_driver.py`
新增公共 API：
```python
def run_custom_script(
    script_path: str,
    batch_folder: str,
    output_mode: str,                  # "save_to_output" | "overwrite" | "no_save"
    output_folder: Optional[str],
    ps_app: str = "Adobe Photoshop 2026",
    on_log_line: Optional[Callable[[str], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> dict
```
内部生成 wrapper jsx：
- 列出 batch_folder 里所有 `.psd`（递归一层）
- 对每个 PSD：
  - `app.open(File(psd))`
  - try/catch `$.evalFile(用户jsx)`
  - 按 output_mode 处理：另存(PhotoshopSaveOptions 到 output_folder) / 保存覆盖 / `close(SaveOptions.DONOTSAVECHANGES)`
  - 写一行进度 `--- (i/n) name.psd ---`（复用 PROGRESS_RE）
  - 检查 cancel marker 文件，存在则 break
- 写最终 result JSON：`{ok, processed, failed, errors: [{file, message}]}`
- 复用 `_drive_ps`、`_tail_log`、`_watch_cancel`、`_to_jsx_string`

### 2. `app/launcher.py`
- 引入 `ttk.Notebook`（CTk 没有自带 Tab，用 tk.ttk 即可；外层包一层 CTkFrame 控制配色）
- `_build_ui` 拆分：
  - `_build_normalizer_tab(parent)` ← 现有内容
  - `_build_script_runner_tab(parent)` ← 新
- Script Runner Tab 字段：
  - 脚本下拉（CTkOptionMenu）+ 浏览按钮：扫描 `app/scripts/` 和 `user_scripts_dirs` 里所有 `.jsx`
  - 「+ 添加脚本目录」按钮 → filedialog → 写回 preset
  - Batch folder：复用 `self.folder_path`（两 Tab 共享）
  - Output mode：CTkSegmentedButton，三选一（默认 save_to_output）
  - RUN / CANCEL 按钮
- 状态条、进度条、output 日志在 Notebook 之外（保持全局），两 Tab 共用
- 新 handler `_on_run_custom_script()`：和 `_on_run` 同构，调 `ps_driver.run_custom_script`

### 3. preset 文件
`~/.tafpsd_presets.json` 顶层结构：
```json
{
  "presets": [...],
  "user_scripts_dirs": ["/Users/.../my-scripts"]
}
```
对应改 `load_presets` / `save_presets`（拆成 `load_user_data` / `save_user_data` 或加新函数）。

### 4. `app/scripts/`
新建目录，放一个示例：
```
_example_flatten.jsx — 演示「合并图层 + 触发 activeDocument」的标准写法
```

### 5. PyInstaller spec
两份 `.spec` 的 `datas` 数组加 `('scripts', 'scripts')`。

### 6. 文档
- `app/README.md` 加 Script Runner 章节（怎么用、脚本怎么写）
- 更新记忆 `project_ta-f_ps-batch.md`

## 风险与注意
- **ExtendScript 路径转义**：所有传入 jsx 的路径都过 `_to_jsx_string`（中文路径坑，见 `feedback_extendscript_gotchas`）
- **`placement` 常量**：本次不涉及图层栈操作，不会踩这个坑
- **AppleEvent timeout (-1712)**：batch 时间长，wrapper 自己写 result JSON，主进程以 JSON 存在与否为准（沿用 normalizer 的做法）
- **PS COM (Windows)**：`DoJavaScript` 同步返回，没问题；同样以 result JSON 为准
- **cancel 检查粒度**：每个 PSD 边界检查一次，和 normalizer 一致
