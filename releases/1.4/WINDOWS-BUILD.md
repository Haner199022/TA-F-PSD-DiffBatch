# Building TA-F PSD DiffBatch 1.4 for Windows

> Mac 上**不能**直接打 Windows `.exe`。下面的步骤必须在 Windows 机器（或 Windows VM）上执行。

## 前置要求

| 必需 | 工具 | 怎么装 |
|---|---|---|
| ✅ | **Python 3.10+** | [python.org/downloads](https://www.python.org/downloads/windows/)，安装时**勾选 "Add Python to PATH"** |
| ✅ | PyInstaller + 项目依赖 | 不用预装，`build.bat` 会自动 `pip install -r requirements.txt` |
| 可选 | **Inno Setup 6** | [jrsoftware.org/isdl.php](https://jrsoftware.org/isdl.php)，仅在你想出单文件 Setup.exe 时需要 |

---

## 步骤 1 · 复制项目到 Windows 工作目录

> ❗ **不要在 iCloud 同步目录里直接打包** — Win 上 iCloud Drive 的"按需下载"会让 PyInstaller 找不到文件。
> ❗ **路径不要含中文** — PyInstaller / Inno Setup / Photoshop COM 都对中文路径敏感。

把整个解压目录拷到本地，例如：
```
D:\dev\PS-BATCH\
```

确认这些文件齐全：
```
D:\dev\PS-BATCH\
├── source\
│   ├── launcher.py / ps_driver.py / normalize_psd.jsx
│   ├── scripts\_example_flatten.jsx
│   ├── assets\logo.png / AppIcon.ico
│   ├── TA-F PSD DiffBatch.spec
│   ├── installer.iss
│   ├── build.bat                ← 一键脚本
│   ├── version_info.txt         ← Win exe 元信息
│   ├── requirements.txt
│   └── README.md
├── WINDOWS-BUILD.md             (本文档)
└── CHANGELOG.md
```

---

## 步骤 2 · 双击 build.bat

打开 `source\` 文件夹，**双击 `build.bat`**。

```
========================================
  TA-F PSD DiffBatch 1.4 - Windows Build
========================================

[1/5] Cleaning previous build artifacts... done.
[2/5] Installing build dependencies (pyinstaller + project requirements)...
[3/5] Building with PyInstaller ("TA-F PSD DiffBatch.spec")...
[4/5] Verifying output...
    dist\TA-F PSD DiffBatch\TA-F PSD DiffBatch.exe  (OK)
[5/5] Done.
========================================
  Build complete.
========================================
```

跑完产出在 `source\dist\TA-F PSD DiffBatch\` 目录下。

**故障排查**：
| 错误 | 解决 |
|---|---|
| `python not found on PATH` | 重装 Python，安装第一步勾"Add to PATH" |
| `pip install failed` | 单跑 `python -m pip install --upgrade pip`，再 `build.bat` |
| `PyInstaller build failed` | 检查 source\ 下源码文件齐不齐；看 PyInstaller 错误日志 |
| `_tkinter` import error | Python 安装时勾上 "tcl/tk and IDLE" 选项 |

---

## 步骤 3 · 测试

```cmd
dist\TA-F PSD DiffBatch\TA-F PSD DiffBatch.exe
```

- 窗口标题 "TA-F PSD DiffBatch" 弹出
- 顶部右上角能看到 Dark / Light / System 三档切换
- 两个 Tab：Normalizer / Script Runner
- Script Runner 下拉里有 `(builtin) _example_flatten.jsx`

通过这几条就算 build 成功。

⚠️ 第一次跑可能蓝色弹"Windows 已保护你的电脑" → 点"更多信息 → 仍要运行"，未签名 .exe 是正常现象。

---

## 步骤 4（可选）· 生成 Setup 安装包

如果只是自用 `.exe`，到第 3 步就结束了。下面是产出**给别人用的单文件安装包**。

1. 装 [Inno Setup 6](https://jrsoftware.org/isdl.php)
2. 双击 `source\installer.iss` → Inno Setup Compiler 自动打开
3. 菜单 **Build → Compile**（或按 F9）
4. 完成后产物在：
```
source\dist\installer\TA-F-PSD-DiffBatch-Setup-1.4.exe
```

把这个文件发给别人：双击 → 安装向导 → 装到 `Program Files\TA-F PSD DiffBatch\` → Start Menu / 桌面快捷方式。

---

## 分发方式对比

| 方式 | 适合场景 | 产物 |
|---|---|---|
| **Portable** | 直接解压双击跑、不想"安装" | zip 整个 `dist\TA-F PSD DiffBatch\` 文件夹 |
| **Installer** | 用户希望"装一下"+ 桌面图标 + 卸载入口 | `Setup-1.4.exe` |

---

## 已知问题

- **首次启动慢**：onedir 模式快；如果以后改 onefile，第一次启动 3-5 秒（解压临时目录）
- **Win Defender 误报**：未签名 PyInstaller .exe 可能被误报，加白名单 / 买代码签名证书可解
- **中文路径**：源码目录、安装位置都建议英文，避免坑

---

## 升级版本号（下次发新版用）

改这 4 处：
1. `installer.iss` 顶部 `#define AppVersion "x.y"`
2. `version_info.txt` 里 `filevers=(x,y,0,0)` / `prodvers` / `FileVersion` / `ProductVersion`
3. `build.bat` 顶部 echo 文案
4. `releases/x.y/` 目录归档

---

## 把产物拷回 Mac 归档

跑完后把以下产物拷回 Mac 的 `releases/1.4/win/`：
```
releases/1.4/
├── ...
└── win/                                              ← 新建
    └── TA-F-PSD-DiffBatch-Setup-1.4.exe              ← 推荐归档这个（自包含）
```

Setup .exe 自身就是自解压安装包，里面已经含 portable folder 全部内容。
