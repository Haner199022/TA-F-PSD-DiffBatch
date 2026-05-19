; =============================================================================
; TA-F PSD DiffBatch — Inno Setup script
;
; 用法（推荐流程）：
;   1. 先双击 build.bat 跑 PyInstaller，产出 dist\TA-F PSD DiffBatch\
;   2. 双击此 installer.iss → Inno Setup Compiler 自动打开
;   3. 菜单 Build → Compile（或按 F9）
;   4. 输出 → dist\installer\TA-F-PSD-DiffBatch-Setup-1.4.exe
;
; 中文路径问题：安装包会把程序装到 C:\Program Files\... 或
; C:\Users\<name>\AppData\Local\Programs\... (纯英文路径)，
; 用户后续在任何 Chinese 路径里启动它都没问题。
; =============================================================================

#define AppName "TA-F PSD DiffBatch"
#define AppVersion "1.4"
#define AppPublisher "TA-F"
#define AppExeName "TA-F PSD DiffBatch.exe"

[Setup]
; 应用元数据
AppId={{C1F0E5A8-7B3D-4F5E-9A1C-2D8E6F3A4B5C}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppVerName={#AppName} {#AppVersion}

; 默认安装到 Program Files\TA-F PSD DiffBatch (纯英文路径，避开中文坑)
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes

; 输出（集中到 dist\installer\ 方便 clean 时整个 dist\ 一次清掉）
OutputDir=dist\installer
OutputBaseFilename=TA-F-PSD-DiffBatch-Setup-{#AppVersion}
SetupIconFile=assets\AppIcon.ico
Compression=lzma2
SolidCompression=yes

; 权限：尝试管理员；如果不允许就装到用户目录
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; 架构 (x64)
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible

; 卸载图标用主程序自带的
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}

; 不需要 Wizard image 资源
WizardStyle=modern
ShowLanguageDialog=auto

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; 把整个 dist\TA-F PSD DiffBatch\ 目录都拷进去（含 .exe + _internal\）
Source: "dist\TA-F PSD DiffBatch\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; 开始菜单
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
; 桌面（可选）
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
; 卸载快捷方式
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

[Run]
; 安装完成后可选立即启动
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
