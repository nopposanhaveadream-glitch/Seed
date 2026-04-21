"""
日次レポートの集計ユーティリティ

使い方:
  python3 scripts/aggregate_reports.py            # 全日分のサマリ表
  python3 scripts/aggregate_reports.py --days 7   # 直近7日分
  python3 scripts/aggregate_reports.py --today    # 今日の詳細
  python3 scripts/aggregate_reports.py --trend    # VE=0比率とQ状態数の推移

日次レポート（~/.seed0/reports/daily_YYYY-MM-DD.json）を読み込んで
よく使うビューを表示する。毎回スクリプトを書き直す手間を省く。
"""

import json
import os
import sys
import glob
import argparse
from datetime import date, timedelta


REPORTS_DIR = os.path.expanduser("~/.seed0/reports")
ALL_ACTIONS = [
    "rest", "sense_body", "write_memory", "sense_deep",
    "diagnose", "adjust_priority", "purge_memory", "clean_temp", "sleep",
]


def load_daily(date_str: str) -> dict:
    """指定日の日次レポートを読み込む。存在しなければNone。"""
    path = os.path.join(REPORTS_DIR, f"daily_{date_str}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def load_all_days() -> list:
    """全日分のレポートを日付順に返す。"""
    files = sorted(glob.glob(os.path.join(REPORTS_DIR, "daily_*.json")))
    days = []
    for f in files:
        date_str = os.path.basename(f).replace("daily_", "").replace(".json", "")
        with open(f) as fh:
            days.append((date_str, json.load(fh)))
    return days


def action_stats(data: dict) -> tuple:
    """(活動率, rest回数, 行動ごとのdict) を返す。sleepingは除外。"""
    actions = dict(data["action_distribution"])
    actions.pop("sleeping", 0)
    total_awake = sum(actions.get(a, 0) for a in ALL_ACTIONS)
    rest_n = actions.get("rest", 0)
    activity_pct = (total_awake - rest_n) / total_awake * 100 if total_awake > 0 else 0
    return activity_pct, rest_n, actions


def cmd_summary(days_filter: int = None):
    """日次サマリ表を表示。"""
    days = load_all_days()
    if days_filter:
        days = days[-days_filter:]

    print(f"{'日付':<12s} {'時間':>4s} {'VE=0%':>6s} {'睡眠':>4s} {'活動%':>5s} {'記憶max':>7s} {'Q状態':>5s} {'Qエントリ':>8s}")
    print("─" * 70)
    for date_str, r in days:
        hrs = len(r["ve_hourly"])
        activity_pct, _, _ = action_stats(r)
        mem_max = max(r["memory_hourly"].values()) if r["memory_hourly"] else 0
        q = r["q_learning"]
        mark = "*" if hrs < 24 else " "
        print(f"{date_str:<12s} {hrs:>3d}h{mark} {r['ve_zero_ratio']*100:>5.2f}% {r['sleep_count']:>4d} {activity_pct:>4.0f}% {mem_max:>7d} {q['states']:>5d} {q['entries']:>8d}")
    print()
    print("* = 部分日（24時間未満）")


def cmd_trend():
    """VE=0比率、Q状態数、記憶最大の推移を可視化。"""
    days = load_all_days()

    print("=== VE=0比率の推移 ===")
    for date_str, r in days:
        hrs = len(r["ve_hourly"])
        bar = "█" * max(1, int(r["ve_zero_ratio"] * 60)) if r["ve_zero_ratio"] > 0 else "·"
        print(f"  {date_str} ({hrs:>2}h): {r['ve_zero_ratio']*100:>5.2f}% {bar}")

    print()
    print("=== Q状態数の推移 ===")
    for i, (date_str, r) in enumerate(days):
        states = r["q_learning"]["states"]
        prev = days[i-1][1]["q_learning"]["states"] if i > 0 else states
        delta = states - prev
        delta_str = f"+{delta}" if delta > 0 else str(delta) if delta < 0 else " 0"
        bar = "▓" * (states // 2)
        print(f"  {date_str}: {states:>3d} ({delta_str}) {bar}")

    print()
    print("=== 記憶最大件数の推移 ===")
    for date_str, r in days:
        mem_max = max(r["memory_hourly"].values()) if r["memory_hourly"] else 0
        bar = "▪" * (mem_max // 10)
        print(f"  {date_str}: {mem_max:>4d}件 {bar}")


def cmd_today():
    """今日分の詳細を表示。"""
    today_str = date.today().isoformat()
    r = load_daily(today_str)
    if not r:
        print(f"今日（{today_str}）のレポートはまだ生成されていません。")
        print("再生成: python3 -c 'from core.daily_report import generate; generate(\"" + today_str + "\")'")
        return

    hrs = len(r["ve_hourly"])
    activity_pct, _, actions = action_stats(r)
    mem_max = max(r["memory_hourly"].values()) if r["memory_hourly"] else 0
    q = r["q_learning"]

    print(f"═══════════════════════════════════════════")
    print(f"  {today_str}  ({hrs}時間分)")
    print(f"═══════════════════════════════════════════")
    print(f"  VE=0比率: {r['ve_zero_ratio']*100:.2f}% ({r['ve_zero_steps']}ステップ)")
    print(f"  睡眠: {r['sleep_count']}回  活動率: {activity_pct:.0f}%")
    print(f"  Q学習: {q['states']}状態/{q['entries']}エントリ  ε={q['epsilon']}")
    print(f"  記憶最大: {mem_max}件")
    print()
    print("  時刻 VE    疲労  記憶   時刻 VE    疲労  記憶")
    print("  ──── ────  ────  ────   ──── ────  ────  ────")
    keys = sorted(r["ve_hourly"].keys(), key=int)
    half = (len(keys) + 1) // 2
    for i in range(half):
        h1 = keys[i]
        left = f"  {int(h1):2d}時 {r['ve_hourly'][h1]:5.1f} {r['fatigue_hourly'][h1]:5.1f} {r['memory_hourly'][h1]:>4}"
        if i + half < len(keys):
            h2 = keys[i + half]
            right = f"   {int(h2):2d}時 {r['ve_hourly'][h2]:5.1f} {r['fatigue_hourly'][h2]:5.1f} {r['memory_hourly'][h2]:>4}"
        else:
            right = ""
        print(left + right)
    print()
    if r["sleep_cycles"]:
        print("  睡眠:")
        for i, s in enumerate(r["sleep_cycles"], 1):
            print(f"    #{i}: {s['sleep_time'][:5]}→{s['wake_time'][:5]} ({s['duration_min']}分) VE:{s['sleep_ve']:.0f}→{s['wake_ve']:.0f}")


def main():
    parser = argparse.ArgumentParser(description="Seed0 日次レポートの集計")
    parser.add_argument("--days", type=int, default=None, help="直近N日分だけ表示")
    parser.add_argument("--today", action="store_true", help="今日の詳細を表示")
    parser.add_argument("--trend", action="store_true", help="VE=0比率・Q状態数・記憶の推移")
    args = parser.parse_args()

    if args.today:
        cmd_today()
    elif args.trend:
        cmd_trend()
    else:
        cmd_summary(args.days)


if __name__ == "__main__":
    main()
