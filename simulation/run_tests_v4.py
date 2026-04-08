"""
Seed0 v4 シミュレーション検証

v3の問題: 正味回復 +0.001/s → VEがほぼゼロに張り付く
v4案B:  rest回復 0.010, BMC軽減 50% → 正味 +0.005/s
案A:    rest回復 0.012, BMC軽減 50% → 正味 +0.007/s

覚醒中のみの指標を分離計測する。
"""

import sys
import os
import json
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = "Hiragino Sans"
import matplotlib.pyplot as plt
import numpy as np
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from simulation.engine import load_phase0_data, SimState, run_simulation


# ─────────────────────────────────────────────
# 分析関数
# ─────────────────────────────────────────────

def analyze_awake_ve(state: SimState) -> dict:
    """覚醒中のVE統計を詳細に分析する。"""
    awake_ve = []
    for i, ve in enumerate(state.ve_log):
        action = state.action_log[i] if i < len(state.action_log) else "none"
        if action != "sleeping":
            awake_ve.append(ve)

    if not awake_ve:
        return {"awake_ve_zero_pct": 0, "awake_ve_mean": 0, "awake_steps": 0}

    awake_ve = np.array(awake_ve)
    zero_count = np.sum(awake_ve <= 0.01)

    return {
        "awake_ve_zero_pct": zero_count / len(awake_ve) * 100,
        "awake_ve_mean": float(np.mean(awake_ve)),
        "awake_ve_median": float(np.median(awake_ve)),
        "awake_ve_min": float(np.min(awake_ve)),
        "awake_ve_max": float(np.max(awake_ve)),
        "awake_ve_p10": float(np.percentile(awake_ve, 10)),
        "awake_ve_p25": float(np.percentile(awake_ve, 25)),
        "awake_ve_p75": float(np.percentile(awake_ve, 75)),
        "awake_steps": len(awake_ve),
        "awake_ve_zero_steps": int(zero_count),
    }


def analyze_actions(state: SimState) -> dict:
    """覚醒中の行動分布を分析する。"""
    awake_actions = [a for a in state.action_log if a != "sleeping"]
    awake_counts = Counter(awake_actions)
    awake_total = len(awake_actions)

    return {
        "awake_total": awake_total,
        "awake_counts": dict(awake_counts),
        "rest_pct": awake_counts.get("rest", 0) / awake_total * 100 if awake_total > 0 else 0,
    }


def analyze_sleep(state: SimState) -> dict:
    """睡眠サイクルを分析する。"""
    if not state.sleep_log:
        return {"sleep_count": 0, "cycles": [], "total_sleep_min": 0,
                "avg_duration_min": 0, "sleep_pct": 0}

    cycles = []
    for start, end in state.sleep_log:
        duration_min = (end - start) * 5.0 / 60
        cycles.append({"start_step": start, "end_step": end,
                       "duration_min": round(duration_min, 1)})

    durations = [c["duration_min"] for c in cycles]
    total_sleep_min = sum(durations)
    total_sim_min = len(state.ve_log) * 5.0 / 60

    return {
        "sleep_count": len(cycles),
        "cycles": cycles,
        "total_sleep_min": round(total_sleep_min, 1),
        "avg_duration_min": round(np.mean(durations), 1),
        "sleep_pct": round(total_sleep_min / total_sim_min * 100, 1) if total_sim_min > 0 else 0,
    }


# ─────────────────────────────────────────────
# シミュレーション実行
# ─────────────────────────────────────────────

def run_variant(data, label, rest_rate, rest_bmc_frac):
    """1つのパラメータセットでシミュレーション実行。"""
    # 正味回復速度を計算して表示
    bmc = 0.01 * 1.0 * rest_bmc_frac
    rebate = 0.01 * 1.0 * (1.0 - rest_bmc_frac)
    net = rest_rate + rebate - 0.01
    print(f"\n{'─' * 50}")
    print(f"  {label}")
    print(f"  rest回復={rest_rate}, BMC軽減={rest_bmc_frac}")
    print(f"  正味回復: {net:+.4f}/s  (VE 0→15: {15/net:.0f}秒={15/net/60:.1f}分)")
    print(f"{'─' * 50}")

    state = SimState(
        rest_ve_recovery_rate=rest_rate,
        rest_bmc_fraction=rest_bmc_frac,
        sleep_fatigue_recovery_rate=0.010,
    )
    steps_24h = min(len(data) - 1, 17280)
    state = run_simulation(data, state, max_steps=steps_24h)
    print(f"  {state.step_count} ステップ完了")
    return state


def print_report(label, state):
    """1バリアントの結果を表示。"""
    awake = analyze_awake_ve(state)
    actions = analyze_actions(state)
    sleep = analyze_sleep(state)

    check_ve0 = "OK" if awake["awake_ve_zero_pct"] < 1 else "NG"
    check_mean = "OK" if awake["awake_ve_mean"] >= 10 else "NG"
    check_med = "OK" if awake["awake_ve_median"] >= 5 else "NG"
    check_rest = "OK" if actions["rest_pct"] <= 85 else "NG"

    print(f"\n  [{label}]")
    print(f"  覚醒中VE=0:    {awake['awake_ve_zero_pct']:6.1f}%  [{check_ve0}] (目標: 0%)")
    print(f"  覚醒中平均VE:  {awake['awake_ve_mean']:6.1f}   [{check_mean}] (目標: >=10)")
    print(f"  覚醒中VE中央値:{awake['awake_ve_median']:6.1f}   [{check_med}] (目標: >=5)")
    print(f"  覚醒中VE p10:  {awake['awake_ve_p10']:6.1f}")
    print(f"  覚醒中VE p25:  {awake['awake_ve_p25']:6.1f}")
    print(f"  覚醒中VE p75:  {awake['awake_ve_p75']:6.1f}")
    print(f"  rest選択率:    {actions['rest_pct']:6.1f}%  [{check_rest}] (目標: <=85%)")
    print(f"  睡眠回数:       {sleep['sleep_count']}")
    print(f"  睡眠合計:       {sleep['total_sleep_min']} 分")
    print(f"  睡眠割合:       {sleep['sleep_pct']}%")
    if sleep["cycles"]:
        for i, c in enumerate(sleep["cycles"]):
            print(f"    #{i+1}: step {c['start_step']}->{c['end_step']} ({c['duration_min']}分)")

    # 行動分布
    print(f"  行動分布（覚醒中）:")
    for a, cnt in sorted(actions["awake_counts"].items(), key=lambda x: -x[1]):
        if a in ("sleeping", "none"):
            continue
        pct = cnt / actions["awake_total"] * 100
        print(f"    {a:<20s}: {cnt:>5} ({pct:5.1f}%)")

    return awake, actions, sleep


def plot_all(variants, output_dir):
    """全バリアントの比較チャート。"""
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle("Seed0 VE回復バランス比較 (v3 / v4-B / v4-A)", fontsize=16, fontweight="bold")

    colors = {"v3": "#E74C3C", "v4-B": "#3498DB", "v4-A": "#2ECC71"}

    # 1. VE推移
    ax = axes[0, 0]
    for label, state in variants.items():
        hours = np.arange(len(state.ve_log)) * 5 / 3600
        ax.plot(hours, state.ve_log, alpha=0.6, label=label,
                color=colors.get(label, "gray"), linewidth=0.5)
    ax.set_title("VE推移（24時間）")
    ax.set_ylabel("VE")
    ax.set_xlabel("時間 (h)")
    ax.legend()
    ax.set_ylim(-5, 105)
    ax.axhline(y=0, color="black", linestyle="--", alpha=0.3)

    # 2. 覚醒中VEヒストグラム
    ax = axes[0, 1]
    for label, state in variants.items():
        awake_ve = [state.ve_log[i] for i in range(len(state.ve_log))
                    if i < len(state.action_log) and state.action_log[i] != "sleeping"]
        ax.hist(awake_ve, bins=50, alpha=0.4, label=label,
                color=colors.get(label, "gray"), density=True)
    ax.set_title("覚醒中VE分布")
    ax.set_xlabel("VE")
    ax.set_ylabel("密度")
    ax.legend()

    # 3. 覚醒中VEの推移（拡大: 最初の覚醒サイクル）
    ax = axes[1, 0]
    for label, state in variants.items():
        # 最初の睡眠開始まで or 最初の7200ステップ(10h)
        if state.sleep_log:
            first_sleep = state.sleep_log[0][0]
        else:
            first_sleep = 7200
        end = min(first_sleep, 7200)
        awake_ve = []
        awake_hours = []
        for i in range(min(end, len(state.ve_log))):
            action = state.action_log[i] if i < len(state.action_log) else "none"
            if action != "sleeping":
                awake_ve.append(state.ve_log[i])
                awake_hours.append(i * 5 / 3600)
        ax.plot(awake_hours, awake_ve, alpha=0.7, label=label,
                color=colors.get(label, "gray"), linewidth=0.8)
    ax.set_title("覚醒中VE推移（第1覚醒サイクル拡大）")
    ax.set_ylabel("VE")
    ax.set_xlabel("時間 (h)")
    ax.legend()
    ax.axhline(y=10, color="orange", linestyle="--", alpha=0.5, label="目標VE>=10")

    # 4. 比較テーブル
    ax = axes[1, 1]
    ax.axis("off")

    headers = ["指標", "v3", "v4-B", "v4-A", "目標"]
    rows = []

    analyses = {}
    for label, state in variants.items():
        awake = analyze_awake_ve(state)
        actions = analyze_actions(state)
        sleep = analyze_sleep(state)
        analyses[label] = (awake, actions, sleep)

    def fmt(v, prec=1):
        return f"{v:.{prec}f}" if isinstance(v, float) else str(v)

    for metric, key, target, getter in [
        ("覚醒中VE=0 (%)", "awake_ve_zero_pct", "0%", lambda a, ac, s: a["awake_ve_zero_pct"]),
        ("覚醒中平均VE", "awake_ve_mean", ">=10", lambda a, ac, s: a["awake_ve_mean"]),
        ("覚醒中VE中央値", "awake_ve_median", ">=5", lambda a, ac, s: a["awake_ve_median"]),
        ("rest選択率 (%)", "rest_pct", "<=85%", lambda a, ac, s: ac["rest_pct"]),
        ("睡眠回数", "sleep_count", "2", lambda a, ac, s: s["sleep_count"]),
        ("睡眠割合 (%)", "sleep_pct", "~20%", lambda a, ac, s: s["sleep_pct"]),
    ]:
        row = [metric]
        for label in ["v3", "v4-B", "v4-A"]:
            if label in analyses:
                val = getter(*analyses[label])
                row.append(fmt(val))
            else:
                row.append("-")
        row.append(target)
        rows.append(row)

    table = ax.table(cellText=[headers] + rows, loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.0, 1.5)
    for j in range(5):
        table[0, j].set_facecolor("#2C3E50")
        table[0, j].set_text_props(color="white", fontweight="bold")
    # v4-BとAの結果セルに色付け
    for row_idx in range(1, len(rows) + 1):
        for col_idx, label in [(2, "v4-B"), (3, "v4-A")]:
            if label not in analyses:
                continue
            # 簡易的な判定色
            val_str = rows[row_idx - 1][col_idx]
            try:
                val = float(val_str)
                if row_idx == 1 and val < 1:  # VE=0 < 1%
                    table[row_idx, col_idx].set_facecolor("#C6EFCE")
                elif row_idx == 2 and val >= 10:  # 平均VE >= 10
                    table[row_idx, col_idx].set_facecolor("#C6EFCE")
                elif row_idx == 3 and val >= 5:  # 中央値 >= 5
                    table[row_idx, col_idx].set_facecolor("#C6EFCE")
                elif row_idx == 4 and val <= 85:  # rest <= 85%
                    table[row_idx, col_idx].set_facecolor("#C6EFCE")
            except ValueError:
                pass

    plt.tight_layout()
    path = os.path.join(output_dir, "v4_comparison.png")
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"\n比較チャート保存: {path}")


def main():
    output_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(output_dir, exist_ok=True)

    print("Phase 0データを読み込み中...")
    data = load_phase0_data()
    print(f"  {len(data)} レコード読み込み完了")

    # v3（ベースライン）
    v3 = run_variant(data, "v3 (rest=0.008, BMC=70%)", 0.008, 0.7)

    # v4-B（案B）
    v4b = run_variant(data, "v4-B (rest=0.010, BMC=50%)", 0.010, 0.5)

    # v4-A（案A）
    v4a = run_variant(data, "v4-A (rest=0.012, BMC=50%)", 0.012, 0.5)

    # レポート出力
    print("\n" + "=" * 60)
    print("  シミュレーション結果比較")
    print("=" * 60)

    results = {}
    for label, state in [("v3", v3), ("v4-B", v4b), ("v4-A", v4a)]:
        awake, actions, sleep = print_report(label, state)
        results[label] = {
            "awake_ve": awake,
            "actions": {k: v for k, v in actions.items() if k != "awake_counts"},
            "action_detail": actions["awake_counts"],
            "sleep": {k: v for k, v in sleep.items() if k != "cycles"},
            "sleep_cycles": sleep["cycles"],
        }

    # 判定サマリー
    print("\n" + "=" * 60)
    print("  判定サマリー")
    print("=" * 60)
    print(f"\n  {'指標':<20s}  {'v3':>8s}  {'v4-B':>8s}  {'v4-A':>8s}  {'目標':>8s}")
    print(f"  {'─'*60}")

    for label in ["v3", "v4-B", "v4-A"]:
        r = results[label]
    # テーブル形式で出力
    metrics = [
        ("覚醒中VE=0 (%)", "awake_ve_zero_pct", "0%"),
        ("覚醒中平均VE", "awake_ve_mean", ">=10"),
        ("覚醒中VE中央値", "awake_ve_median", ">=5"),
        ("覚醒中VE p25", "awake_ve_p25", "-"),
        ("rest選択率 (%)", None, "<=85%"),
        ("睡眠回数", None, "2"),
        ("睡眠割合 (%)", None, "~20%"),
    ]
    for name, key, target in metrics:
        vals = []
        for label in ["v3", "v4-B", "v4-A"]:
            r = results[label]
            if key and key in r["awake_ve"]:
                vals.append(f"{r['awake_ve'][key]:6.1f}")
            elif name == "rest選択率 (%)":
                vals.append(f"{r['actions']['rest_pct']:6.1f}")
            elif name == "睡眠回数":
                vals.append(f"{r['sleep']['sleep_count']:>6}")
            elif name == "睡眠割合 (%)":
                vals.append(f"{r['sleep']['sleep_pct']:6.1f}")
            else:
                vals.append("     -")
        print(f"  {name:<20s}  {vals[0]}  {vals[1]}  {vals[2]}  {target:>8s}")

    # チャート
    plot_all({"v3": v3, "v4-B": v4b, "v4-A": v4a}, output_dir)

    # JSON保存
    # numpy値をfloat変換
    def convert(obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return obj

    results_path = os.path.join(output_dir, "results_v4.json")
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=convert)
    print(f"\n結果JSON保存: {results_path}")


if __name__ == "__main__":
    main()
