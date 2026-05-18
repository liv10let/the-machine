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
┌─────────────────┐     cron 每5分钟      ┌──────────────┐
│ 飞书日历 API    │ ──────────────────→ │ focus-guard  │
│ (当前日程)      │                     │ (检测逻辑)    │
└─────────────────┘                     └──────┬───────┘
                                               │
                    ┌──────────────────────────┼──────────┐
                    │                          │          │
              ┌─────▼─────┐           ┌──────▼──────┐ ┌──▼────────┐
              │ AW PC端   │           │ AW AFK      │ │ AW Android│
              │ 浏览器/窗口│           │ 离开检测    │ │ 手机活动  │
              └───────────┘           └─────────────┘ └───────────┘
                    │                          │
                    │         AFK 时跳过 PC     │
                    └──────────────────────────┘
                                               │
                                        ┌─────▼─────┐
                                        │ 飞书卡片  │
                                        │ 分心提醒  │
                                        └───────────┘
```

## 快速开始

### 1. 前置依赖

- Python 3.8+
- [ActivityWatch](https://activitywatch.net/) 服务端（本地或远程）
- [lark-cli](https://github.com/openclaw/openclaw/tree/main/clients/lark-cli)（用于读取飞书日历）
- 飞书自建应用（用于发送消息卡片）

### 2. 安装

```bash
git clone https://github.com/liv10let/the-machine.git
cd the-machine
# 可选：创建虚拟环境
python -m venv venv && source venv/bin/activate
pip install python-dateutil  # 唯一的外部依赖
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

## AFK 检测原理

```
1. 查询 aw-watcher-afk 最近事件
2. 检查当前时刻是否落在 AFK 事件区间内
3. 如果是 AFK → 跳过 PC 端 bucket（浏览器 + 窗口）
4. 手机端 bucket 不受影响（手机使用不依赖电脑状态）
```

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
