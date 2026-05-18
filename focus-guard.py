#!/usr/bin/env python3
"""
The Machine (focus-guard.py) — 专注守卫
名字来源：《疑犯追踪》(Person of Interest) 中的监控 AI "The Machine"
在飞书日历有工作/学习/DDL日程时，检测是否在刷分心 app/网站，发飞书卡片提醒。
零 LLM token 消耗，纯规则。

使用 lark-cli 调飞书 API（复用已有用户认证），AW 直接 HTTP 调用。
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ============================================================
# 配置（从环境变量读取，支持 .env 文件）
# ============================================================

# 优先从 .env 文件加载（如果存在）
def _load_dotenv():
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_file):
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key not in os.environ:
                        os.environ[key] = val

_load_dotenv()

# 飞书机器人配置（用于发消息）
FEISHU_APP_ID     = os.environ.get("THE_MACHINE_FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.environ.get("THE_MACHINE_FEISHU_APP_SECRET", "")
FEISHU_CHAT_ID    = os.environ.get("THE_MACHINE_FEISHU_CHAT_ID", "")

# lark-cli 日历 ID（主日历）
CALENDAR_ID = os.environ.get("THE_MACHINE_CALENDAR_ID", "")

# ActivityWatch 配置
AW_API_BASE = os.environ.get("THE_MACHINE_AW_API_BASE", "http://localhost:5600/api/0")
AW_AUTH     = os.environ.get("THE_MACHINE_AW_AUTH", "")

# lark-cli 路径（自动探测，也可通过环境变量覆盖）
LARK_CLI_PATH = os.environ.get("THE_MACHINE_LARK_CLI", "")
if not LARK_CLI_PATH:
    # 尝试自动探测
    for candidate in [
        "/root/.nvm/versions/node/v22.22.2/bin/lark-cli",
        "/usr/local/bin/lark-cli",
        "/usr/bin/lark-cli",
    ]:
        if os.path.exists(candidate):
            LARK_CLI_PATH = candidate
            break
    if not LARK_CLI_PATH:
        # 尝试从 PATH 中找
        for d in os.environ.get("PATH", "").split(":"):
            candidate = os.path.join(d, "lark-cli")
            if os.path.exists(candidate):
                LARK_CLI_PATH = candidate
                break

# 排除守卫的日程颜色（休息/自由时间用这些颜色标记）
# 默认不排除任何颜色，所有日程都触发守卫
EXCLUDE_COLORS = set()

# 冷却期（秒）
COOLDOWN_SECONDS = 30 * 60  # 30 分钟

# 冷却状态文件
COOLDOWN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "focus-guard-cooldown.json")

# 最小停留时间（秒），低于此值视为误触/自动加载，不算分心
MIN_DISTRACTION_SECONDS = 60

# 分心域名列表
DISTRACTION_DOMAINS = {
    "bilibili.com", "xiaohongshu.com", "douyin.com",
    "weibo.com", "youtube.com", "taobao.com", "jd.com",
    "zhihu.com", "douban.com", "tieba.baidu.com",
    "weibo.cn", "tiktok.com", "instagram.com",
    "twitter.com", "x.com", "reddit.com",
    "jandan.net",
    "manhuagui.com",
}

# 分心手机 app 关键词（包名 + 中文名）
DISTRACTION_ANDROID_KEYWORDS = {
    "bilibili", "douyin", "xingin.xhs", "weibo",
    "taobao", "jingdong", "zhihu", "douban",
    "tiktok", "instagram", "twitter",
    "小红书", "抖音", "哔哩哔哩", "b站", "bilibili",
    "微博", "淘宝", "京东", "知乎", "豆瓣",
}

# 分心 PC 应用名关键词
DISTRACTION_PC_KEYWORDS = {
    "bilibili", "douyin", "weibo", "taobao",
    "jd.com", "xiaohongshu", "bilibili.exe",
}

# 日志目录（按天分文件，JSONL 格式）
LOG_DIR = Path(os.path.dirname(os.path.abspath(__file__))) / "focus-guard-logs"

# ============================================================
# 工具函数
# ============================================================

# cron 环境 PATH 不全，手动补上
os.environ["PATH"] = "/root/.nvm/versions/node/v22.22.2/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

CST = timezone(timedelta(hours=8))


# ============================================================
# 结构化日志（JSONL，按天分文件）
# ============================================================

def now_cst():
    return datetime.now(CST)


def log_write(level, event, **kwargs):
    """写一条结构化日志到 focus-guard-logs/YYYY-MM-DD.log"""
    LOG_DIR.mkdir(exist_ok=True)
    ts = now_cst()
    entry = {
        "ts": ts.strftime("%Y-%m-%d %H:%M:%S"),
        "level": level,
        "event": event,
    }
    if kwargs:
        entry.update(kwargs)
    log_file = LOG_DIR / f"{ts.strftime('%Y-%m-%d')}.log"
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[ERROR] 写日志失败: {e}", file=sys.stderr)


def http_json(url, method="GET", data=None, headers=None, auth=None):
    """发起 HTTP 请求，返回 JSON"""
    hdrs = headers or {}
    if data is not None:
        data = json.dumps(data).encode("utf-8")
        hdrs["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)

    if auth:
        import base64
        cred = base64.b64encode(auth.encode()).decode()
        req.add_header("Authorization", f"Basic {cred}")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        log_write("error", "http_error", url=url, code=e.code, body=body[:500])
        return None
    except Exception as e:
        log_write("error", "http_failed", url=url, error=str(e))
        return None


def lark_cli(*args):
    """调用 lark-cli 命令，返回 JSON"""
    if not LARK_CLI_PATH or not os.path.exists(LARK_CLI_PATH):
        log_write("error", "lark_cli_not_found", path=LARK_CLI_PATH)
        return None

    cmd = [LARK_CLI_PATH] + list(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            log_write("error", "lark_cli_failed", args=list(args), stderr=result.stderr[:500])
            return None
        return json.loads(result.stdout)
    except Exception as e:
        log_write("error", "lark_cli_exception", args=list(args), error=str(e))
        return None


# ============================================================
# 飞书：获取 tenant_access_token（用于发消息）
# ============================================================

_token_cache = {"token": None, "expires": 0}


def get_tenant_token():
    now = time.time()
    if _token_cache["token"] and _token_cache["expires"] > now:
        return _token_cache["token"]

    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        log_write("error", "tenant_token_no_creds")
        return None

    resp = http_json(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        method="POST",
        data={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
    )
    if not resp or resp.get("code") != 0:
        log_write("error", "tenant_token_failed", resp=resp)
        return None

    token = resp["tenant_access_token"]
    expire = resp.get("expire", 7200)
    _token_cache["token"] = token
    _token_cache["expires"] = now + expire - 60
    return token


def feishu_send_message(data):
    """用 tenant token 发飞书消息"""
    token = get_tenant_token()
    if not token:
        return None
    url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
    return http_json(url, method="POST", data=data, headers={
        "Authorization": f"Bearer {token}",
    })


# ============================================================
# 飞书：获取当前进行中的日程（通过 lark-cli）
# ============================================================

def get_current_events():
    """获取当前时刻正在进行的日程"""
    now = now_cst()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)

    start_ts = str(int(start.timestamp()))
    end_ts = str(int(end.timestamp()))

    params = json.dumps({
        "calendar_id": CALENDAR_ID,
        "start_time": start_ts,
        "end_time": end_ts,
    })

    resp = lark_cli("calendar", "events", "instance_view", "--params", params)
    if not resp or resp.get("code", -1) != 0:
        log_write("error", "calendar_fetch_failed", resp=resp)
        return []

    items = resp.get("data", {}).get("items", [])
    now_ts = now.timestamp()

    current = []
    for ev in items:
        st = ev.get("start_time", {})
        et = ev.get("end_time", {})

        if st.get("timestamp"):
            ev_start = int(st["timestamp"])
            ev_end = int(et.get("timestamp", ev_start + 3600))
        else:
            continue

        if ev_start <= now_ts <= ev_end:
            color = ev.get("color", -1)
            current.append({
                "event_id": ev.get("event_id"),
                "summary": ev.get("summary", "(无标题)"),
                "color": color,
                "start": ev_start,
                "end": ev_end,
            })

    return current


# ============================================================
# ActivityWatch：查询最近 N 分钟事件
# ============================================================

def aw_get_events(bucket, minutes=5):
    """获取 AW bucket 最近 N 分钟的事件（AW 用 UTC 时间）"""
    now = datetime.now(timezone.utc)
    end_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    start_str = (now - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")

    url = f"{AW_API_BASE}/buckets/{bucket}/events?start={start_str}&end={end_str}&limit=100"
    events = http_json(url, auth=AW_AUTH)
    if events is None:
        return []
    return events


def _domain_match(domain, url):
    """精确域名匹配，避免子串误匹配（如 x.com 匹配 itssx.com）"""
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        # 检查主机名是否正好是 domain 或以 .domain 结尾
        if host == domain or host.endswith("." + domain):
            return True
    except Exception:
        pass
    return False


def _fmt_duration(seconds):
    """格式化秒数为人类可读时长"""
    if seconds < 60:
        return f"{int(seconds)}秒"
    elif seconds < 3600:
        return f"{int(seconds // 60)}分{int(seconds % 60)}秒"
    else:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}小时{m}分" if m else f"{h}小时"


def is_distracting_event(event):
    """判断一个 AW 事件是否分心，返回 (bool, detail_dict_or_None)"""
    # 过滤停留时间过短的事件（误触/自动加载）
    duration = event.get("duration", 0)
    if duration < MIN_DISTRACTION_SECONDS:
        return False, None

    data = event.get("data", {})
    title = data.get("title", "")
    url = data.get("url", "")
    app = data.get("app", "")

    # 计算起止时间
    ts_str = event.get("timestamp", "")
    start_time = ""
    end_time = ""
    if ts_str:
        try:
            from dateutil.parser import parse as parse_dt
            start_dt = parse_dt(ts_str)
            end_dt = start_dt + timedelta(seconds=duration)
            # 转换到 CST
            cst = timezone(timedelta(hours=8))
            start_dt = start_dt.astimezone(cst)
            end_dt = end_dt.astimezone(cst)
            start_time = start_dt.strftime("%H:%M:%S")
            end_time = end_dt.strftime("%H:%M:%S")
        except Exception:
            pass

    # 检查浏览器 URL
    if url:
        for domain in DISTRACTION_DOMAINS:
            if _domain_match(domain, url):
                return True, {
                    "type": "web",
                    "reason": f"🌐 {domain}",
                    "domain": domain,
                    "title": title,
                    "url": url,
                    "duration": duration,
                    "duration_text": _fmt_duration(duration),
                    "start_time": start_time,
                    "end_time": end_time,
                }

    # 检查 PC 应用名
    app_lower = app.lower()
    for kw in DISTRACTION_PC_KEYWORDS:
        if kw in app_lower:
            return True, {
                "type": "pc",
                "reason": f"💻 {app}",
                "app": app,
                "title": title,
                "duration": duration,
                "duration_text": _fmt_duration(duration),
                "start_time": start_time,
                "end_time": end_time,
            }

    # 检查手机 app 包名
    for kw in DISTRACTION_ANDROID_KEYWORDS:
        if kw in app_lower:
            return True, {
                "type": "android",
                "reason": f"📱 {app}",
                "app": app,
                "title": title,
                "duration": duration,
                "duration_text": _fmt_duration(duration),
                "start_time": start_time,
                "end_time": end_time,
            }

    return False, None


def is_pc_afk():
    """检查当前用户是否在电脑前（AFK 状态）。
    查询 aw-watcher-afk_HAL-9000 最近事件，
    如果最新事件的 status 为 afk 且覆盖当前时刻，返回 True。
    """
    events = aw_get_events("aw-watcher-afk_HAL-9000", minutes=5)
    if not events:
        # 没有 AFK 数据时，默认认为用户在电脑前（保守策略）
        return False

    # AW events 按时间倒序排列，最新事件在前
    now_utc = datetime.now(timezone.utc)
    for ev in events:
        status = ev.get("data", {}).get("status", "")
        ts_str = ev.get("timestamp", "")
        duration = ev.get("duration", 0)
        if not ts_str:
            continue
        try:
            from dateutil.parser import parse as parse_dt
            ev_start = parse_dt(ts_str)
            ev_end = ev_start + timedelta(seconds=duration)
            # 如果事件覆盖了当前时刻
            if ev_start <= now_utc <= ev_end:
                return status == "afk"
        except Exception:
            continue

    # 没有覆盖当前时刻的 AFK 事件，默认不认为 AFK
    return False


def check_distractions():
    """检查所有 AW bucket 的最近事件，返回分心发现列表（按 app 去重，保留最长 duration）。
    PC 端 bucket（浏览器 + 窗口）在用户 AFK 时自动跳过。
    """
    # 检查 AFK 状态，决定是否跳过 PC 端 bucket
    pc_afk = is_pc_afk()
    if pc_afk:
        log_write("info", "pc_afk_skip", reason="用户 AFK，跳过 PC 端 bucket 检测")

    buckets = [
        "aw-watcher-web-firefox_server",
        "aw-watcher-window_HAL-9000",
        "aw-watcher-android-realtime",
    ]

    findings_map = {}  # key: reason, value: detail dict

    for bucket in buckets:
        # PC 端 bucket 在 AFK 时跳过
        if pc_afk and bucket in ("aw-watcher-web-firefox_server", "aw-watcher-window_HAL-9000"):
            continue

        events = aw_get_events(bucket, minutes=5)
        for ev in events:
            is_dist, detail = is_distracting_event(ev)
            if is_dist and detail:
                reason = detail["reason"]
                if reason not in findings_map:
                    findings_map[reason] = detail
                else:
                    # 同一 app 出现多次，保留 duration 最长的
                    if detail["duration"] > findings_map[reason]["duration"]:
                        findings_map[reason] = detail

    return list(findings_map.values())


# ============================================================
# 冷却期管理
# ============================================================

def load_cooldown():
    try:
        with open(COOLDOWN_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_cooldown(data):
    with open(COOLDOWN_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_cooled_down(reason):
    """检查某个分心原因是否在冷却期内"""
    cd = load_cooldown()
    last_ts = cd.get(reason, 0)
    return (time.time() - last_ts) < COOLDOWN_SECONDS


def mark_cooled_down(reason):
    """标记某个分心原因已被提醒"""
    cd = load_cooldown()
    cd[reason] = time.time()
    # 清理超过 1 小时的旧记录
    now = time.time()
    cd = {k: v for k, v in cd.items() if (now - v) < 3600}
    save_cooldown(cd)


# ============================================================
# 飞书：发送卡片消息
# ============================================================

def send_focus_card(findings, event_summary):
    """发送分心提醒卡片（带详细信息 + 交互按钮）"""
    # 构建分心详情文本
    detail_lines = []
    for f in findings:
        time_info = ""
        if f.get('start_time') and f.get('end_time'):
            time_info = f" ⏱ {f['start_time']} ~ {f['end_time']}"
        line = f"**{f['reason']}** — {f['duration_text']}{time_info}"
        if f.get('title'):
            line += f"\n    📄 {f['title']}"
        if f.get('url'):
            # 截断过长 URL
            url = f['url']
            if len(url) > 80:
                url = url[:77] + "..."
            line += f"\n    🔗 {url}"
        detail_lines.append(line)
    distraction_text = "\n\n".join(detail_lines)

    # 为每个分心项生成按钮
    action_elements = []
    for f in findings:
        reason_short = f['reason'].split(" ", 1)[-1] if " " in f['reason'] else f['reason']
        reason_key = f['reason']  # 用于冷却期的 key
        action_elements.append({
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": f"✅ 正常用途（{reason_short}）"},
                    "type": "default",
                    "value": {"action": "ack", "reason": reason_key, "event": event_summary},
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": f"🔥 我在摸鱼（{reason_short}）"},
                    "type": "danger",
                    "value": {"action": "caught", "reason": reason_key, "event": event_summary},
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": f"❌ 误报（{reason_short}）"},
                    "type": "default",
                    "value": {"action": "false_alarm", "reason": reason_key, "event": event_summary},
                },
            ],
        })

    # 计算总分心时长
    total_secs = sum(f.get('duration', 0) for f in findings)
    total_text = _fmt_duration(total_secs)

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "🤖 The Machine 已锁定"},
            "template": "red",
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**当前日程**：{event_summary}\n\n"
                        f"**检测到 {len(findings)} 项分心行为**（累计 {total_text}）：\n\n"
                        f"{distraction_text}"
                    ),
                },
            },
            {"tag": "hr"},
            *action_elements,
            {"tag": "hr"},
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": "✅ 正常用途 = 30分钟冷却  |  🔥 摸鱼 = 下次还提醒  |  ❌ 误报 = 不冷却不计入",
                    }
                ],
            },
        ],
    }

    resp = feishu_send_message({
        "receive_id": FEISHU_CHAT_ID,
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False),
    })

    if resp and resp.get("code") == 0:
        return True
    else:
        log_write("error", "send_card_failed", resp=resp)
        return False


# ============================================================
# 主流程
# ============================================================

def main():
    log_write("info", "check_start")

    # 1. 检查当前是否有工作/学习/DDL 日程
    events = get_current_events()
    if not events:
        log_write("info", "skip", reason="no_events")
        return

    non_excluded = [e for e in events if e["color"] not in EXCLUDE_COLORS]

    if not non_excluded:
        log_write("info", "skip", reason="all_excluded")
        return

    ev = non_excluded[0]
    event_summary = ev["summary"]
    log_write("info", "current_event", summary=event_summary, color=ev["color"],
              event_id=ev.get("event_id"))

    # 2. 检查 AW 分心行为
    findings = check_distractions()
    if not findings:
        log_write("info", "clean", summary=event_summary)
        return

    # 3. 冷却期过滤
    cooled = [f for f in findings if is_cooled_down(f["reason"])]
    new_findings = [f for f in findings if not is_cooled_down(f["reason"])]
    if not new_findings:
        log_write("info", "all_cooled", findings=[f["reason"] for f in findings], cooled=[f["reason"] for f in cooled])
        return

    log_write("info", "distraction_found", summary=event_summary,
              findings=[f["reason"] for f in findings], cooled=[f["reason"] for f in cooled],
              new_findings=[f["reason"] for f in new_findings])

    # 4. 发送提醒（不自动设冷却，由回调处理：ack=冷却，caught=不冷却）
    if send_focus_card(new_findings, event_summary):
        log_write("info", "alert_sent", findings=[f["reason"] for f in new_findings], summary=event_summary)
    else:
        log_write("error", "alert_failed", findings=[f["reason"] for f in new_findings], summary=event_summary)


if __name__ == "__main__":
    main()
