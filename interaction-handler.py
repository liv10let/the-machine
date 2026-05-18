#!/usr/bin/env python3
"""
interaction-handler.py — 飞书卡片按钮回调处理示例

配套 focus-guard.py 使用。当用户在飞书卡片上点击按钮时，
你的 OpenClaw / 飞书事件监听服务会收到回调，调用此脚本处理。

支持的 action：
- ack        → 正常用途，设 30 分钟冷却
- caught     → 确认摸鱼，不设冷却（下次继续提醒）
- false_alarm → 误报，记录但不设冷却

用法（OpenClaw 飞书长连接回调中）：
    python3 interaction-handler.py --action ack --reason "🌐 jandan.net"
"""

import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta

COOLDOWN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "focus-guard-cooldown.json")
INTERACTION_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "focus-guard-interactions.jsonl")
COOLDOWN_SECONDS = 30 * 60

CST = timezone(timedelta(hours=8))


def load_cooldown():
    try:
        with open(COOLDOWN_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_cooldown(data):
    with open(COOLDOWN_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def log_interaction(action, reason, event_summary=""):
    """记录用户交互到 JSONL"""
    entry = {
        "ts": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "reason": reason,
        "event": event_summary,
    }
    with open(INTERACTION_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def handle(action, reason, event_summary=""):
    """处理用户点击"""
    log_interaction(action, reason, event_summary)

    if action == "ack":
        cd = load_cooldown()
        cd[reason] = time.time()
        # 清理旧记录
        now = time.time()
        cd = {k: v for k, v in cd.items() if (now - v) < 3600}
        save_cooldown(cd)
        print(f"✅ 已确认正常用途：{reason}，冷却 30 分钟")

    elif action == "caught":
        print(f"🔥 收到坦白：{reason}，不设冷却，下次继续提醒")

    elif action == "false_alarm":
        print(f"❌ 已记录误报：{reason}，不计入统计")

    else:
        print(f"⚠️ 未知 action: {action}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="处理飞书卡片按钮回调")
    parser.add_argument("--action", required=True, choices=["ack", "caught", "false_alarm"])
    parser.add_argument("--reason", required=True)
    parser.add_argument("--event", default="")
    args = parser.parse_args()

    handle(args.action, args.reason, args.event)
