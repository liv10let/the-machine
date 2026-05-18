# The Machine — 专注守卫 🤖

> 名字来源：《疑犯追踪》(Person of Interest) 中的监控 AI "The Machine"

一个**零 LLM token 消耗、纯规则驱动**的专注守卫系统。当你的飞书日历上有工作/学习/DDL 日程时，它会通过 [ActivityWatch](https://activitywatch.net/) 检测你是否在刷分心 App/网站，并发飞书卡片提醒。

## 核心特性

- **零 LLM 消耗**：纯规则判断，不需要任何大模型 API
- **AFK 智能判断**：检测到用户离开电脑（AFK 状态）时，自动忽略 PC 端的分心事件，避免误报
- **多平台覆盖**：同时监控 PC 浏览器、PC 应用、Android 手机
- **交互式反馈**：飞书卡片带按钮（正常用途 / 我在摸鱼 / 误报），支持冷却期管理
- **结构化日志**：JSONL 格式，按天分文件，方便后续分析
- **精确域名匹配**：避免子串误匹配（如 `x.com` 不会误匹配 `itssx.com`）

## 运行架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         数据采集端（各端魔改 watcher）                          │
├──────────────┬──────────────┬──────────────┬──────────────┬─────────────────┤
│   PC 浏览器   │   PC 窗口     │   PC AFK     │  Android 手机 │   VS Code       │
│              │              │              │              │                 │
│ 魔改浏览器插件 │ 魔改窗口监听  │  魔改AFK监听  │  aw-android-  │  魔改VSCode插件  │
│  TypeScript  │   Kotlin     │   Python     │    plus      │   TypeScript    │
└──────┬───────┴──────┬───────┴──────┬───────┴──────┬───────┴────────┬────────┘
       │              │              │              │                 │
       └──────────────┴──────────────┴──────────────┴─────────────────┘
                                    │
                              HTTP POST (带 Basic Auth)
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          数据汇聚层（远程 AW Server）                         │
│                                                                             │
│   运行在远程服务器的 aw-server-rust，接收并存储所有 watcher 的心跳数据       │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                              HTTP GET
                           (focus-guard.py 查询)
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          检测层（The Machine）                               │
│                                                                             │
│   1. 查询飞书日历 → 是否有工作/学习日程？                                    │
│   2. 查询 AFK bucket → 用户是否在电脑前？                                    │
│   3. AFK 时跳过 PC 端 bucket（浏览器 + 窗口）                               │
│   4. 查询 Android bucket → 手机是否在分心？                                  │
│   5. 命中后发送飞书卡片提醒                                                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 这不是标准的 ActivityWatch

⚠️ **重要说明**：本系统依赖的不是官方 ActivityWatch，而是**魔改版 watcher**，它们将数据从各端设备**实时转发到远程服务器**上。标准 ActivityWatch 只在本地存储数据，无法被远程检测。

### 数据链路全景

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         数据采集端（各端魔改 watcher）                          │
├──────────────┬──────────────┬──────────────┬──────────────┬─────────────────┤
│   PC 浏览器   │   PC 窗口     │   PC AFK     │  Android 手机 │   VS Code       │
│              │              │              │              │                 │
│ 魔改浏览器插件 │ 魔改窗口监听  │  魔改AFK监听  │  aw-android-  │  魔改VSCode插件  │
│  TypeScript  │   Kotlin     │   Python     │    plus      │   TypeScript    │
└──────┬───────┴──────┬───────┴──────┬───────┴──────┬───────┴────────┬────────┘
       │              │              │              │                 │
       └──────────────┴──────────────┴──────────────┴─────────────────┘
                                    │
                              HTTP POST
                            (带 Basic Auth)
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          数据汇聚层（远程 AW Server）                         │
│                                                                             │
│   运行在远程服务器的 aw-server-rust，接收并存储所有 watcher 的心跳数据       │
│   通过 nginx 反向代理 + Basic Auth 提供安全访问                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                              HTTP GET
                           (focus-guard.py 查询)
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          检测层（The Machine）                               │
│                                                                             │
│   focus-guard.py 通过 AW API 拉取各 bucket 的最近事件                         │
│   结合飞书日历判断是否有工作/学习日程                                          │
│   结合 AFK 状态智能过滤误报                                                  │
│   命中分心行为后发送飞书卡片提醒                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 各端 watcher 与对应仓库

| 数据源 | Bucket 名称 | 魔改仓库 | 魔改内容 | 语言 |
|--------|------------|----------|---------|------|
| **PC 浏览器** | `aw-watcher-web-firefox_server` | [aw-watcher-web-firefox](https://github.com/liv10let/aw-watcher-web-firefox) | 将心跳数据从本地转发到远程服务器，支持自定义 URL | TypeScript |
| **PC 窗口** | `aw-watcher-window_HAL-9000` | [aw-watcher-window-crossplatform](https://github.com/liv10let/aw-watcher-window-crossplatform) | 跨平台窗口监听 + 远程 HTTP 转发 | Kotlin |
| **PC AFK** | `aw-watcher-afk_HAL-9000` | [aw-watcher-afk](https://github.com/liv10let/aw-watcher-afk) | 键盘鼠标活动检测 + 远程 HTTP 转发 | Python |
| **Android 实时** | `aw-watcher-android-realtime` | [aw-android-plus](https://github.com/liv10let/aw-android-plus) | AccessibilityService 实时 App 切换 + 远程 HTTP 转发 + AFK 检测 | Kotlin |
| **VS Code** | `aw-watcher-vscode` | [aw-watcher-vscode](https://github.com/liv10let/aw-watcher-vscode) | 编辑器活动监听 + 远程 HTTP 转发 + 登录功能防数据泄露 | TypeScript |

> **HAL-9000** 是 bucket 的后缀名，对应设备名。如果你有多个设备，每台设备的 watcher 都会带上各自的主机名后缀。

### 远程服务器搭建

所有魔改 watcher 的数据都汇聚到一台远程服务器上的 `aw-server-rust`：

```nginx
# nginx 配置示例：反向代理 + Basic Auth
server {
    listen 5601;
    auth_basic "ActivityWatch";
    auth_basic_user_file /etc/nginx/.htpasswd;
    location / {
        proxy_pass http://127.0.0.1:5600;
    }
}
```

客户端 watcher 配置远程地址：`http://your-server:5601`，带上 Basic Auth 凭证。

## 前置依赖

### 服务端（必选）

- [aw-server-rust](https://github.com/ActivityWatch/aw-server-rust) 运行在远程服务器
- nginx 反向代理（推荐，用于 Basic Auth 和 SSL）

### 客户端（至少选一个）

你需要在要监控的设备上安装对应的魔改 watcher：

| 你想监控的设备 | 需要安装的仓库 |
|--------------|--------------|
| PC 浏览器 | [aw-watcher-web-firefox](https://github.com/liv10let/aw-watcher-web-firefox) |
| PC 窗口 + AFK | [aw-watcher-window-crossplatform](https://github.com/liv10let/aw-watcher-window-crossplatform) + [aw-watcher-afk](https://github.com/liv10let/aw-watcher-afk) |
| Android 手机 | [aw-android-plus](https://github.com/liv10let/aw-android-plus) |
| VS Code | [aw-watcher-vscode](https://github.com/liv10let/aw-watcher-vscode) |

### The Machine 本体

- Python 3.8+
- [lark-cli](https://github.com/openclaw/openclaw/tree/main/clients/lark-cli)（用于读取飞书日历）
- 飞书自建应用（用于发送消息卡片）
- `python-dateutil`（`pip install python-dateutil`）

## 安装

```bash
git clone https://github.com/liv10let/the-machine.git
cd the-machine
python -m venv venv && source venv/bin/activate
pip install python-dateutil
```

### 3. 配置

复制示例配置并填写：

```bash
cp .env.example .env
```

编辑 `.env`：

```ini
# 飞书机器人（用于发消息）
THE_MACHINE_FEISHU_APP_ID=cli_xxx
THE_MACHINE_FEISHU_APP_SECRET=your-app-secret
THE_MACHINE_FEISHU_CHAT_ID=oc_xxx          # 目标群聊或用户 ID

# 日历配置
THE_MACHINE_CALENDAR_ID=feishu.cn_xxx@group.calendar.feishu.cn

# ActivityWatch
THE_MACHINE_AW_API_BASE=http://localhost:5600/api/0
THE_MACHINE_AW_AUTH=awuser:awpass          # Basic Auth 凭证
```

### 4. 配置分心规则

编辑 `focus-guard.py` 中的以下集合：

- `DISTRACTION_DOMAINS` — 分心网站域名
- `DISTRACTION_PC_KEYWORDS` — PC 应用名关键词
- `DISTRACTION_ANDROID_KEYWORDS` — 手机 App 关键词

### 5. 设置定时任务

```bash
crontab -e
```

添加（每5分钟检测一次）：

```cron
*/5 * * * * /usr/bin/python3 /path/to/the-machine/focus-guard.py >> /path/to/the-machine/focus-guard-cron.log 2>&1
```

## 交互按钮

飞书卡片提供三种按钮：

| 按钮 | 行为 |
|------|------|
| ✅ 正常用途 | 该分心项进入 30 分钟冷却期 |
| 🔥 我在摸鱼 | 不冷却，下次继续提醒 |
| ❌ 误报 | 不冷却，且不计入统计 |

> **注意**：按钮回调需要你的 OpenClaw 或其他飞书事件监听服务来处理。详见 `interaction-handler.py` 示例。

## 文件说明

| 文件 | 说明 |
|------|------|
| `focus-guard.py` | 核心检测脚本 |
| `interaction-handler.py` | 飞书卡片按钮回调处理示例 |
| `.env.example` | 环境变量配置模板 |
| `focus-guard-logs/` | 运行日志（JSONL，自动生成） |
| `focus-guard-cooldown.json` | 冷却期状态文件（自动生成） |

## 日志分析

日志文件为 JSONL 格式，可直接用 `jq` 分析：

```bash
# 查看今天的所有分心发现
cat focus-guard-logs/$(date +%Y-%m-%d).log | jq 'select(.event=="distraction_found")'

# 统计今天误报次数
cat focus-guard-logs/$(date +%Y-%m-%d).log | jq -s '[.[] | select(.event=="false_alarm")] | length'
```

## AFK 检测原理（防误报关键）

```
1. 查询 aw-watcher-afk_HAL-9000 最近事件
2. 检查当前时刻是否落在 AFK 事件区间内（status == "afk"）
3. 如果是 AFK → 跳过 PC 端 bucket：
   - aw-watcher-web-firefox_server（浏览器）
   - aw-watcher-window_HAL-9000（窗口）
4. 手机端 bucket 不受影响：
   - aw-watcher-android-realtime（Android 实时 App 切换）
```

> **为什么这样设计？** 当用户离开电脑时，浏览器可能还停留在一个分心网站上（如 jandan.net），但这不代表用户正在浏览。通过 `aw-watcher-afk` 的键盘/鼠标活动检测，可以准确判断用户是否还在电脑前。

## 各端 bucket 与配置

focus-guard.py 默认监控以下 bucket：

| Bucket | 数据来源 | 魔改仓库 | 说明 |
|--------|---------|----------|------|
| `aw-watcher-web-firefox_server` | PC Firefox | [aw-watcher-web-firefox](https://github.com/liv10let/aw-watcher-web-firefox) | 浏览器标签页和 URL |
| `aw-watcher-window_HAL-9000` | PC 窗口 | [aw-watcher-window-crossplatform](https://github.com/liv10let/aw-watcher-window-crossplatform) | 当前活跃窗口标题 |
| `aw-watcher-afk_HAL-9000` | PC AFK | [aw-watcher-afk](https://github.com/liv10let/aw-watcher-afk) | 键盘鼠标活动状态 |
| `aw-watcher-android-realtime` | Android | [aw-android-plus](https://github.com/liv10let/aw-android-plus) | 实时 App 切换（AccessibilityService） |

> **HAL-9000** 是你的设备名。如果你有多个设备，每台设备的 watcher 都会生成带各自主机名后缀的 bucket。在 `focus-guard.py` 中修改 bucket 名称以匹配你的设备名。

## 自定义

### 调整灵敏度

- `MIN_DISTRACTION_SECONDS`：默认 60 秒，低于此值的停留视为误触
- `COOLDOWN_SECONDS`：默认 30 分钟，点击「正常用途」后的冷却期

### 排除特定日程颜色

```python
EXCLUDE_COLORS = {0, 1}  # 0=蓝色, 1=紫色（休息/自由时间）
```

## License

MIT © [liv10let](https://github.com/liv10let)
