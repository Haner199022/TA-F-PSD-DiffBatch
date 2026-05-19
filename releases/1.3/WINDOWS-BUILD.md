# Windows 打包指南 · TA-F PSD DiffBatch v1.3

按这份文档在 Windows 上跑一次就能产出：
- `TA-F PSD DiffBatch.exe`（PyInstaller 文件夹 build，可直接双击运行）
- `TA-F-PSD-DiffBatch-Setup-1.3.exe`（Inno Setup 单文件安装包，给别人用）

预计耗时：第一次 ≈ 30 分钟（含装环境），熟练后 ≈ 5 分钟。

---

## 0 · 准备：把源码拷到 Windows

把整个 `releases/1.3/source/` 目录拷到 Windows，建议放在**纯英文路径**下，例如：

```
D:\TA-F\PS-BATCH-1.3\
```

⚠️ **避免**：路径里含中文、空格、emoji。PyInstaller 和 Inno Setup 都对路径敏感，中文会出怪问题。

---

## 1 · 装 Python 3.10+

1. 打开 https://www.python.org/downloads/windows/
2. 下载 **Windows installer (64-bit)**，版本 3.10 ~ 3.12 都行（3.13 也可，但生态略新）
3. 跑安装包，**第一步勾上「Add python.exe to PATH」**（关键！否则后面命令找不到）
4. 安装完打开 CMD，验证：

```cmd
python --version
pip --version
```

两条都应该返回版本号。如果没有，重启电脑或检查 PATH。

---

## 2 · 装项目依赖

打开 CMD，cd 到源码目录：

```cmd
cd /d D:\TA-F\PS-BATCH-1.3
pip install -r requirements.txt
```

会装下面这些包（`requirements.txt` 里写好了，自动处理）：

| 包 | 用途 |
|---|---|
| pyinstaller | 打 .exe |
| customtkinter | GUI 框架 |
| tkinterdnd2 | 拖拽支持 |
| psd-tools, Pillow | 右侧 PSD 缩略图 |
| **pywin32** | **Windows 必需 — 通过 COM 驱动 PS** |

装完验证 PyInstaller：

```cmd
pyinstaller --version
```

应该返回 `6.x.x`。

---

## 3 · PyInstaller 打 .exe

源码目录下直接跑 spec 文件：

```cmd
pyinstaller "TA-F PSD DiffBatch.spec"
```

需要 1-3 分钟。完成后产物在：

```
D:\TA-F\PS-BATCH-1.3\dist\TA-F PSD DiffBatch\
├── TA-F PSD DiffBatch.exe       ← 主程序
├── _internal\                   ← 依赖（不可删）
└── ...
```

**快速验证**：双击 `TA-F PSD DiffBatch.exe`，窗口能弹出、能切两个 Tab、Script Runner 下拉里有 `(builtin) _example_flatten.jsx` 就说明 PyInstaller 这一步没问题。

⚠️ 如果出现「Windows 已保护你的电脑」蓝色弹窗 → 点「更多信息」→「仍要运行」。未签名的可执行文件第一次跑都会被 SmartScreen 拦，正常现象。

⚠️ 杀软可能误报 → 加白名单。打包工具产物常被启发式查杀。

---

## 4 · Inno Setup 打安装包（可选，分发给别人时用）

如果只是自用 `.exe`，到第 3 步就结束了。下面是产出**给别人用的安装包**的步骤。

### 4.1 装 Inno Setup 6

1. 下载：https://jrsoftware.org/isdl.php （Inno Setup 6）
2. 默认安装即可

### 4.2 编译

1. **关键**：把 `installer.iss` 文件放到 `D:\TA-F\PS-BATCH-1.3\` 下（也就是 `dist\` 的**父目录**）—— `installer.iss` 顶部的 `Source: "dist\TA-F PSD DiffBatch\*"` 是相对路径，依赖这个位置
2. 双击 `installer.iss` → Inno Setup Compiler 打开
3. 菜单 **Build → Compile**（或按 F9）
4. 完成后产物在：

```
D:\TA-F\PS-BATCH-1.3\installer_output\
└── TA-F-PSD-DiffBatch-Setup-1.3.exe   ← 这就是发给别人的安装包
```

---

## 5 · 把产物拷回 Mac 归档

把 Windows 产物拷回 Mac 的 `releases/1.3/` 下：

```
releases/1.3/
├── CHANGELOG.md
├── source/
├── mac/
│   ├── TA-F PSD DiffBatch.app
│   └── TA-F-PSD-DiffBatch-1.3-mac.zip
└── win/                                     ← 新建
    ├── TA-F PSD DiffBatch/                  ← 文件夹版（PyInstaller 产物，可选）
    └── TA-F-PSD-DiffBatch-Setup-1.3.exe     ← 安装包（推荐归档这个）
```

只归档 Setup .exe 也够用（它本身就是自解压安装包，包含了所有 PyInstaller 产物）。

---

## 常见坑

| 现象 | 原因 / 解决 |
|---|---|
| `'pyinstaller' is not recognized` | Python 没装好或 PATH 没设。重装 Python 并勾上「Add to PATH」 |
| PyInstaller 报 `ImportError: No module named 'pywin32'` | requirements.txt 装失败，单独跑 `pip install pywin32` |
| 双击 .exe 没反应 / 闪退 | 在 CMD 里跑 `.exe` 看 stderr。多半是 PS 没装或不能识别。`ps_driver.py` 里 PS 通过 `Photoshop.Application` COM 找，要求 PS 正常装好并至少跑过一次 |
| 安装到中文路径报错 | 改装到 `C:\Program Files\TA-F PSD DiffBatch\`（installer.iss 默认就是英文路径，照默认走即可） |
| Inno Setup 报「找不到 dist\...」 | installer.iss 没放对位置。必须和 `dist\` 文件夹同级，不是放在 `dist\` 里 |
| SmartScreen 拦截 | 未签名是正常的。点「更多信息 → 仍要运行」。要彻底解决需要花钱买代码签名证书 |

---

## 关于代码签名（要不要做）

- **自用**：不用，SmartScreen 弹一次「仍要运行」就 OK
- **小范围分发**（给几个同事）：不用，告知他们点「仍要运行」即可
- **大范围分发 / 商业发布**：建议买证书（EV 证书 ≈ $250-400/年），签了之后 SmartScreen 不再拦
- 工具：`signtool.exe`（Windows SDK 自带）

---

## TL;DR 快速命令

```cmd
cd /d D:\TA-F\PS-BATCH-1.3
pip install -r requirements.txt
pyinstaller "TA-F PSD DiffBatch.spec"
:: 然后 Inno Setup Compiler 打开 installer.iss, F9
```
