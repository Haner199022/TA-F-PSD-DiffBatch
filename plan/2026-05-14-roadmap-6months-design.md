---
title: PS-BATCH 6 个月路线图设计 (v1.3 → v1.5)
type: design-spec
created: 2026-05-14
status: approved
source: brainstorming via superpowers:brainstorming skill
related:
  - "[[project_ta-f_ps-batch]]"
  - "[[project_ta-f]]"
tags:
  - ta-f
  - ps-batch
  - roadmap
  - design
---

# PS-BATCH 6 个月路线图设计

## 1. 一句话目标
2026-05 → 2026-11：把 PS-BATCH 从"个人 packshot 工具"变成 **"3-5 个 Windows 同事自助使用的团队工具"**，北极星 = 同事能自己安装+更新，不需要问维护者。

## 2. 已确认的约束

| 维度 | 决定 |
|---|---|
| 终点状态 | 3-5 同事的团队工具 |
| 北极星 | 同事自助安装+更新 |
| 分发渠道 | 公司 NAS（`\\nas\TA-F\PS-BATCH\`，可写） |
| 平台 | **全 Windows**，Mac 完全拿出（含架构预留） |
| 时间预算 | 每周 8-15 小时 |
| 更新方式 | **后台自动应用更新**（不是手动点 setup.exe） |
| alpha 制度 | v1.3 release 前置条件：必须有 1 个同事人选 |

## 3. 路线图骨架

```
2026-05 ──────────────────────────────────────► 2026-11

  v1.3 (~10w, May-Jul)     v1.4 (~10w, Jul-Sep)      v1.5 (~6w, Oct-Nov)
  后台自动更新              RUN BATCH 结构变换         团队化收尾
  + 1 同事 alpha           (PS 端深活)               (共享脚本+错误友好)

总: 26w ≈ 6.5 个月（比原计划溢出 2 周，可接受）
```

### YAGNI 红线（明确不做）

1. ❌ Mac 支持（含架构预留）—— 现无 Mac 同事，未来需要时另开 v1.6+ 项目
2. ❌ License / 付费层 —— 终点是团队工具，非商业产品
3. ❌ 多更新通道（stable / beta）—— 全员同一 channel

## 4. v1.3 详细设计（May-Jul，~10 周）

### 4.1 主题
**后台自动更新基础设施 + alpha 验证**

### 4.2 架构

```
启动时
  ├─ 读取嵌入版本号 (1.3.0)
  ├─ 后台线程：尝试访问 \\nas\TA-F\PS-BATCH\latest.json (超时 3s)
  │    └─ NAS 不通 → 静默跳过 (offline-tolerant)
  └─ 若 NAS 版本 > 本地版本
       ├─ 后台下载 .exe 到临时目录（带校验和）
       ├─ 弹窗：「v1.3.1 已下载。重启工具应用？[Yes][Later][Mute v1.3.1]」
       ├─ Yes → 自更新流程：
       │        1. 主进程启动 setup.exe 为子进程（setup 内部 wait 主进程退出）
       │        2. 主进程退出
       │        3. setup 替换并安装新版本（此时 .exe 已无锁）
       │        4. setup 启动新版本
       ├─ Later → 下次启动再问
       └─ Mute → 持久化到 muted_versions[]，跳过同版本
```

### 4.3 NAS 文件夹结构

```
\\nas\TA-F\PS-BATCH\
├── latest.json              ← {version, exe_url, exe_sha256, changelog, mandatory:false}
├── releases\
│   ├── PSDNormalizer-1.3.0-setup.exe
│   ├── PSDNormalizer-1.3.1-setup.exe
│   └── ...
└── README.md                ← 5 分钟上手（Help 菜单链接到这里）
```

### 4.4 v1.3 范围内（must-have）

- [ ] `app/updater.py` 模块（~400-600 LOC，纯 stdlib 优先）
  - [ ] `check_for_update()` —— 后台线程，超时 3s
  - [ ] `download_update()` —— 带 SHA256 校验
  - [ ] `apply_update()` —— 解锁→ relaunch 自更新进程
  - [ ] `mute_version()` / `is_muted()` —— 偏好持久化
- [ ] launcher.py 集成：启动时调用，非阻塞
- [ ] UAC 权限场景测试（同事机器可能锁定）
- [ ] 杀软白名单文档（万一被拦）
- [ ] `latest.json` schema 文档
- [ ] NAS 上一次性手动放好 1.3.0 + README + 文件夹结构
- [ ] Help 菜单 → "Onboarding"（打开 NAS 上的 README）
- [ ] **找到 1 个 alpha 同事并约定时间窗**（release 前置条件，未确认 TODO）

### 4.5 v1.3 明确不做

- ❌ 增量更新（整包替换）
- ❌ 回滚机制（NAS 上手动保留旧版本就够）
- ❌ 遥测 / 使用统计（先靠口头反馈）
- ❌ Mac 兼容代码（YAGNI）

### 4.6 v1.3 DoD（Definition of Done）

1. ✅ alpha 同事的机器自动收到版本提示
2. ✅ alpha 同事按提示完整走完一次升级（无你介入）
3. ✅ NAS 不通时工具正常启动（不卡死）
4. ✅ 你自己用 v1.3 跑过 ≥ 5 次真实 packshot 任务无回归

## 5. v1.4 概要（Jul-Sep，~10 周）

### 5.1 主题
**RUN BATCH 从"名字匹配"升级为"结构变换"**（PS 端深活）

### 5.2 关键改造（详见 `[[project_ta-f_ps-batch]]` 第 30-42 行）

1. **智能匹配**：名字锚点 → 找不到回退到位置匹配
2. **自动转 Smart Object**：调用 `newPlacedLayer` action
3. **重放 filter chain**：复用现有逻辑
4. **自动创建蒙版**：从 Before 每层 alpha 通道生成（**不是**从 After 复制）
5. 多余 Before 层 → 删除
6. 蒙版应用范围 = After 里有蒙版的对应层

### 5.3 同步更新点

- `normalize_psd.jsx` line 425-466 的 apply 逻辑

### 5.4 v1.4 DoD

用户原话："经过对比后所有案例都和 after 文件效果一致"

### 5.5 中点 check（第 5 周）

如超期，可砍 "多余 Before 层删除"到 v1.5 polish，保 v1.4 主线进度。

## 6. v1.5 概要（Oct-Nov，~6 周）

### 6.1 主题
**团队化收尾 —— 让北极星真正落地**

### 6.2 子项 1：共享脚本库（~3 周）

- NAS 新建 `\\nas\TA-F\PS-BATCH\team_scripts\`
- Script Runner Tab 启动时自动扫描，加进下拉列表（不写本地 preset）
- 团队任何人改 .jsx 全员立即可用
- 命名约定 + 简单 README

### 6.3 子项 2：错误友好化（~3 周）

- 错误弹窗加 "复制诊断信息" 按钮（PSD 路径 + log + 版本号一键打包）
- 常见错误的人话翻译（如 "PS not responding" → "PS 卡住了，先关掉 PS 再点重试"）
- 排查向导：5-6 个最常见问题的"如果…请…"

## 7. 跨版本横切关注点

| 主题 | 决定 |
|---|---|
| NAS 文件夹布局 | `\\nas\TA-F\PS-BATCH\{latest.json, releases\, team_scripts\, README.md}`（所有版本沿用） |
| 版本号 | semver。v1.x.0 = 主版本，v1.x.y = 修补 |
| 发版流程 | 本地打包 → 测试 → 上传 NAS `releases\` → 更新 `latest.json` → alpha 同事自动收到 |
| alpha 同事制度 | v1.3 release 前置条件。**TODO：定人选** |
| 文档承诺 | 每个主版本必须更新 NAS 上 `README.md` |
| 回归测试 | 跑 ≥ 5 次真实 packshot 任务才算主版本完成（DoD 之一） |

## 8. Top 3 风险

| 风险 | 等级 | 应对 |
|---|---|---|
| alpha 同事未找到 | 🔴 高 | 1 周内必须定人选，否则 v1.3 启动延后 |
| NAS 不稳定 / 速度慢 | 🟡 中 | v1.3 NAS 访问做超时 3s + 静默 fallback，先验证再依赖 |
| v1.4 结构变换超期 | 🟡 中 | 第 5 周中点 check，超期砍"多余 Before 层删除"到 v1.5 |
| 自更新进程被杀软拦 | 🟡 中 | v1.3 内准备杀软白名单文档 + 失败时降级回手动 setup.exe |

## 9. 6 个月末成功指标

北极星可量化版本：

- ✅ ≥ 3 名同事装上 PS-BATCH 且过去 30 天用过 ≥ 1 次
- ✅ 过去 30 天内你**没收到过**关于"怎么装 / 怎么更新"的求助
- ✅ NAS 上 `team_scripts/` 有 ≥ 2 个非你提交的脚本
- ✅ v1.5 release 时回归测试全过

## 10. 开放 TODO（spec 通过后立即处理）

- [ ] **定 alpha 同事人选**（v1.3 启动前置条件）
- [ ] 跟 IT 确认 `\\nas\TA-F\PS-BATCH\` 文件夹权限（写权限 + 同事读权限）
- [ ] 决定杀软白名单需要 IT 配合还是用户自己加

## 11. 后续步骤

设计批准后，进入 `superpowers:writing-plans` skill，把 v1.3（最近一个版本）拆解为可执行的实现计划。v1.4/v1.5 在各自启动前再单独 plan。
