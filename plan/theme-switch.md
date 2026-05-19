---
title: v1.4 · UI 明暗主题三档切换
status: done
created: 2026-05-15
completed: 2026-05-16
---

## 落地确认（2026-05-16）

三档切换已在 `app/launcher.py` 中实施完毕。用户决策：
1. 浅色 ok/danger/warn = 加深版 `#16A34A / #DC2626 / #D97706`
2. SegmentedButton 标签 = 英文 `Dark / Light / System`
3. 全新安装默认 = `System`（跟随系统）

代码定位：
- M_DARK / M_LIGHT / C(key) / _current_palette() — `launcher.py:176-219`
- 启动读 preset + 默认 System fallback — `launcher.py:162-173`
- appbar SegmentedButton — `launcher.py:599-619`
- _on_theme_change + PanedWindow 手工 reconfigure — `launcher.py:1414-1424`
- 持久化 `save_appearance_mode` — `launcher.py:91-97`

---


# v1.4 第一步 · 明暗主题切换

## 目标
现在 launcher 只有深色模式（`ctk.set_appearance_mode("dark")` + 配色硬编码在 M 字典）。改成三档切换：**深色 / 浅色 / 跟随系统**。浅色风格 = 纯白底黑字（与深色镜像对称）。

## 用户决策
- 入口位置：appbar 右侧放 CTkSegmentedButton 三档切换
- 浅色配色：纯白底 + 黑字，保持 1Password / TA-F 单色风
- 切换实时生效（不需重启）
- 持久化：写到 `~/.tafpsd_presets.json` 的 `appearance_mode` 键

## 设计

### 1. 配色 palette 重构

把当前的 `M` 字典扩展为 `M_DARK` + `M_LIGHT`，并加一个 `M` 全局变量动态指向当前活跃 palette：

```python
M_DARK = {
    "bg":          "#000000",
    "surface":     "#111111",
    "surface_2":   "#1A1A1A",
    "divider":     "#2A2A2A",
    "primary":     "#FFFFFF",
    "primary_dk":  "#CCCCCC",
    "on_primary":  "#000000",
    "secondary":   "#BBBBBB",
    "text_hi":     "#FFFFFF",
    "text_md":     "#AAAAAA",
    "text_lo":     "#666666",
    "ok":          "#22C55E",
    "danger":      "#EF4444",
    "warn":        "#F59E0B",
}

M_LIGHT = {
    "bg":          "#FFFFFF",   # 纯白
    "surface":     "#FFFFFF",   # 卡片同底（用 border 区分）
    "surface_2":   "#F5F5F5",   # 输入框/低对比
    "divider":     "#E0E0E0",   # 浅灰
    "primary":     "#000000",   # 纯黑按钮
    "primary_dk":  "#333333",   # hover 略浅
    "on_primary":  "#FFFFFF",   # 黑按钮上的白字
    "secondary":   "#444444",   # in-progress 强调色
    "text_hi":     "#000000",
    "text_md":     "#555555",
    "text_lo":     "#999999",
    "ok":          "#16A34A",   # 浅色背景下加深的 green
    "danger":      "#DC2626",
    "warn":        "#D97706",
}
```

### 2. 双值传参（CTk 原生机制）

CTk 大多数 `fg_color` / `text_color` 参数支持 `(light_value, dark_value)` 元组形式——根据 `set_appearance_mode()` 自动取对应那个。

这意味着**不需要遍历重 configure 所有 widget**——配色定义改成元组，CTk 自动跟随。

实施方式：把所有 `fg_color=M["xxx"]` 重构成 `fg_color=(M_LIGHT["xxx"], M_DARK["xxx"])` 或者用一个 helper：

```python
def C(key: str) -> tuple:
    """Return a (light, dark) tuple for a palette key — CTk auto-picks by mode."""
    return (M_LIGHT[key], M_DARK[key])
```

然后所有 widget 创建处用 `fg_color=C("bg")` 替代 `fg_color=M["bg"]`。

⚠️ **例外**：用 `tk.PanedWindow`（不是 CTk）的地方（`_build_ui` 第 489-495 行）不支持元组——需要手工监听模式切换并重 configure。

### 3. 切换控件 UI

appbar 右侧加 `CTkSegmentedButton`，三档：
```
[ Dark | Light | System ]
```

绑定 `command=self._on_theme_change`，调用 `ctk.set_appearance_mode("dark"|"light"|"system")`，然后保存到 preset。

### 4. 持久化

复用现有 `_load_userdata` / `_save_userdata`，加 `appearance_mode` 键。启动时读取并应用：

```python
mode = _load_userdata().get("appearance_mode", "dark")
ctk.set_appearance_mode(mode)
```

启动顺序：在 `ctk.set_appearance_mode(...)` 调用前完成（即文件顶部的 `ctk.set_appearance_mode("dark")` 改成动态读取）。

### 5. PanedWindow 特殊处理

`tk.PanedWindow` 的 `bg` 参数不支持元组。监听 CTk 的内部 `_set_appearance_mode` 事件不可行，简单方案：

- 启动时按当前模式 set 一次
- 切换时 `_on_theme_change` 里手工 reconfigure：`self.split.configure(bg=M["divider"])`，其中 `M` 此时是动态计算的

为此需要一个 `_current_palette() -> dict` 函数：

```python
def _current_palette() -> dict:
    return M_LIGHT if ctk.get_appearance_mode() == "Light" else M_DARK
```

CTk 在 `system` 模式下会返回 `"Dark"` 或 `"Light"`（实际生效值），所以这函数也能正确返回。

## 改动文件清单

| 文件 | 改动 |
|---|---|
| `launcher.py` 顶部 M 字典 | 拆成 `M_DARK` + `M_LIGHT`，加 `C(key)` helper，保留 `M` 作为兼容别名（暂时） |
| `launcher.py` 所有 widget 创建 | `M["xxx"]` → `C("xxx")` （正则替换 + 手工检查 PanedWindow / non-CTk widget） |
| `launcher.py` `set_appearance_mode` | 从硬编码 `"dark"` 改为读 preset |
| `launcher.py` appbar | 加 SegmentedButton 三档切换 |
| `launcher.py` __init__ | 加 `self._on_theme_change` 方法 |
| preset 文件 | 新增 `appearance_mode` 键 |
| memory `project_ta-f_ps-batch.md` | 记录 v1.4 第一个功能 |

## 估计改动规模

- launcher.py：~80 行改动（多数是 `M["xxx"]` → `C("xxx")` 的机械替换）
- 测试：headless 构造 + 三档切换互动测试 + 浅色模式视觉检查

## 风险
- **CTkProgressBar 的 progress_color**：要确认支持元组（CTk 各版本支持度不同）。验证方式：实测
- **PanedWindow + tk.Listbox / messagebox / filedialog** 用系统主题，无法跟随 CTk —— 接受这一点，不强求统一
- **SegmentedButton 在切换时 selected 视觉反馈**：浅色模式下 selected = 黑按钮，对比要够强（已在 palette 里准备）
- **跟随系统模式下 macOS auto theme**：CTk 用 `darkdetect` 库自动检测，应该 work；最差情况是不响应实时系统切换，但启动时跟随是确定的
- **既有 widget 已经写死 `text_color="black"` / 类似硬编码**：grep 一遍 `M\[` 替换不到的，单独处理（比如 launcher.py 里少量 segmented_button_selected_color 等）

## 待用户确认

1. 浅色模式下的 `ok`/`danger`/`warn` 颜色（绿/红/橙）我用了加深版本（#16A34A 等），可以吗？还是想保持鲜亮度？
2. SegmentedButton 三档的标签用英文（Dark / Light / System）还是中文（深色 / 浅色 / 系统）？我倾向英文（和现有所有界面文字一致）
3. 启动默认值：preset 没有 `appearance_mode` 键时默认 "dark"（保持老用户体验）还是 "system"（跟随系统更现代）？
