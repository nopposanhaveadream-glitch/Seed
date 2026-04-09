"""
Seed0 Phase 1 — 日次レポート生成

agent.logをパースして、1日分のサマリーをJSONファイルに出力する。
これはSeed0の行動ではなく、観察者のためのツール。
代謝に影響を与えない（VEコストなし）。

出力先: ~/.seed0/reports/daily_YYYY-MM-DD.json
"""

import json
import os
import re
from collections import defaultdict

# レポートの出力先
REPORT_DIR = os.path.expanduser("~/.seed0/reports")

# ログファイルのデフォルトパス
LOG_PATH = os.path.expanduser("~/.seed0/logs/agent.log")

# ログ行のパターン
# ステップログ: "2026-04-09 07:42:33,514 [INFO] [ 9613] rest  | VE= 44.3 ..."
_STEP_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}) (\d{2}):\d{2}:\d{2},\d+ \[INFO\] "
    r"\[\s*(\d+)\] "              # step番号
    r"(\S+)\s+\| "                # 行動名
    r"VE=\s*([\d.]+).*?"          # VE値
    r"疲労=\s*([\d.]+).*?"         # 疲労値
    r"記憶=(\d+)"                  # 記憶件数
)

# 睡眠ログ: "💤 入眠 | VE=26.7 | 疲労=30.3 | step=2278"
_SLEEP_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}),\d+ \[INFO\] "
    r"💤 入眠 \| VE=([\d.]+) \| 疲労=([\d.]+) \| step=(\d+)"
)

# 起床ログ: "☀️ 起床 | VE=61.3 | 疲労=10.0 | step=2685"
_WAKE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}),\d+ \[INFO\] "
    r"☀️ 起床 \| VE=([\d.]+) \| 疲労=([\d.]+) \| step=(\d+)"
)

# Q学習サマリー: "Q値=42状態/182エントリ"
_Q_RE = re.compile(r"Q値=(\d+)状態/(\d+)エントリ")

# εサマリー: "ε=0.138"
_EPSILON_RE = re.compile(r"ε=([\d.]+)")


def generate(target_date: str, log_path: str = LOG_PATH) -> str:
    """
    指定日のログを解析し、日次レポートJSONを生成する。

    target_date: "YYYY-MM-DD" 形式の日付文字列
    log_path: agent.logのパス
    returns: 出力したJSONファイルのパス
    """
    # 1時間ごとの集計用
    # キー: 時間（0〜23）、値: その時間帯の最後のステップの値
    hourly_ve = {}
    hourly_fatigue = {}
    hourly_memory = {}

    # 行動カウント
    action_counts = defaultdict(int)

    # VE=0カウント
    ve_zero_count = 0
    total_steps = 0

    # 睡眠サイクル
    sleep_cycles = []
    pending_sleep = None  # 入眠中で起床待ち

    # Q学習（日末時点の最新値）
    q_states = 0
    q_entries = 0
    epsilon = 0.0

    # 現在読んでいる行が対象日に属しているかを追跡
    current_line_date = None

    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            # 日付付きの行なら現在の日付を更新
            date_match = re.match(r"^(\d{4}-\d{2}-\d{2})", line)
            if date_match:
                current_line_date = date_match.group(1)

            # ステップログのパース
            m = _STEP_RE.match(line)
            if m:
                date_str = m.group(1)
                if date_str != target_date:
                    continue

                hour = int(m.group(2))
                step = int(m.group(3))
                action = m.group(4)
                ve = float(m.group(5))
                fatigue = float(m.group(6))
                memory = int(m.group(7))

                # 1時間ごとの最新値を記録（上書き）
                hourly_ve[hour] = round(ve, 1)
                hourly_fatigue[hour] = round(fatigue, 1)
                hourly_memory[hour] = memory

                # 行動カウント
                action_counts[action] += 1

                # VE=0カウント
                if ve < 0.1:
                    ve_zero_count += 1
                total_steps += 1
                continue

            # 睡眠ログのパース
            m = _SLEEP_RE.match(line)
            if m:
                date_str = m.group(1)
                if date_str != target_date:
                    continue
                pending_sleep = {
                    "sleep_time": m.group(2),
                    "sleep_ve": float(m.group(3)),
                    "sleep_fatigue": float(m.group(4)),
                    "sleep_step": int(m.group(5)),
                }
                continue

            # 起床ログのパース
            m = _WAKE_RE.match(line)
            if m:
                date_str = m.group(1)
                # 起床が翌日でも、入眠が対象日なら含める
                if pending_sleep is not None:
                    wake_time = m.group(2)
                    wake_ve = float(m.group(3))
                    wake_fatigue = float(m.group(4))
                    wake_step = int(m.group(5))

                    duration_steps = wake_step - pending_sleep["sleep_step"]
                    duration_min = round(duration_steps * 5 / 60, 1)

                    sleep_cycles.append({
                        "sleep_time": pending_sleep["sleep_time"],
                        "wake_time": wake_time,
                        "wake_date": date_str,
                        "duration_min": duration_min,
                        "sleep_ve": pending_sleep["sleep_ve"],
                        "wake_ve": wake_ve,
                        "sleep_fatigue": pending_sleep["sleep_fatigue"],
                        "wake_fatigue": wake_fatigue,
                    })
                    pending_sleep = None
                continue

            # Q学習サマリーのパース（60秒サマリーの中にある非日付行）
            # 直前のステップログの日付が対象日なら対象
            if current_line_date == target_date:
                m_q = _Q_RE.search(line)
                if m_q:
                    q_states = int(m_q.group(1))
                    q_entries = int(m_q.group(2))

                m_e = _EPSILON_RE.search(line)
                if m_e:
                    epsilon = float(m_e.group(1))

    # VE=0比率
    ve_zero_ratio = round(ve_zero_count / total_steps, 4) if total_steps > 0 else 0.0

    # レポート組み立て
    report = {
        "date": target_date,
        "total_steps": total_steps,
        "ve_hourly": hourly_ve,
        "fatigue_hourly": hourly_fatigue,
        "memory_hourly": hourly_memory,
        "sleep_cycles": sleep_cycles,
        "sleep_count": len(sleep_cycles),
        "q_learning": {
            "states": q_states,
            "entries": q_entries,
            "epsilon": epsilon,
        },
        "ve_zero_ratio": ve_zero_ratio,
        "ve_zero_steps": ve_zero_count,
        "action_distribution": dict(action_counts),
    }

    # 出力
    os.makedirs(REPORT_DIR, exist_ok=True)
    output_path = os.path.join(REPORT_DIR, f"daily_{target_date}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return output_path
