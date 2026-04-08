"""
Seed0 v3 シミュレーション検証

v2からの変更:
  - rest回復率: 0.005 → 0.008 VE/秒
  - rest中のBMC軽減: 通常の70%（30%リベート）

v3で解消すべき問題:
  - 覚醒中のVE=0が83%（実機Phase 1初回起動で発覚）

検証指標（依頼書より）:
  1. 覚醒中のVE=0の時間割合（0%が目標）
  2. 覚醒中の平均VE（10以上が望ましい）
  3. 睡眠サイクルへの影響（覚醒10h/睡眠2.4hが崩れないか）
  4. rest選択率の変化（80%から大きく変わらないか）
"""

import sys
import os
import json
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = "Hiragino Sans"
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from simulation.engine import (
    load_phase0_data, SimState, run_simulation
)


def analyze_awake_ve(state: SimState) -> dict:
    """覚醒中のVE統計を詳細に分析する。"""
    awake_ve = []
    awake_ve_zero_steps = 0
    awake_steps = 0

    for i, ve in enumerate(state.ve_log):
        action = state.action_log[i] if i < len(state.action_log) else "none"
        if action != "sleeping":
            awake_steps += 1
            awake_ve.append(ve)
            if ve <= 0.01:  # 実質ゼロ
                awake_ve_zero_steps += 1

    if awake_steps == 0:
        return {"awake_ve_zero_pct": 0, "awake_ve_mean": 0, "awake_steps": 0}

    return {
        "awake_ve_zero_pct": awake_ve_zero_steps / awake_steps * 100,
        "awake_ve_mean": np.mean(awake_ve) if awake_ve else 0,
        "awake_ve_min": np.min(awake_ve) if awake_ve else 0,
        "awake_ve_max": np.max(awake_ve) if awake_ve else 0,
        "awake_ve_median": np.median(awake_ve) if awake_ve else 0,
        "awake_steps": awake_steps,
        "awake_ve_zero_steps": awake_ve_zero_steps,
    }


def analyze_actions(state: SimState) -> dict:
    """行動分布を分析する。"""
    from collections import Counter
    total = len(state.action_log)
    counts = Counter(state.action_log)

    # 覚醒中の行動のみ
    awake_actions = [a for a in state.action_log if a != "sleeping"]
    awake_counts = Counter(awake_actions)
    awake_total = len(awake_actions)

    return {
        "total": total,
        "counts": dict(counts),
        "awake_total": awake_total,
        "awake_counts": dict(awake_counts),
        "rest_pct": awake_counts.get("rest", 0) / awake_total * 100 if awake_total > 0 else 0,
    }


def analyze_sleep_cycles(state: SimState) -> dict:
    """睡眠サイクルを分析する。"""
    if not state.sleep_log:
        return {"sleep_count": 0, "cycles": []}

    cycles = []
    for start, end in state.sleep_log:
        duration_min = (end - start) * 5.0 / 60  # ステップ数 × 5秒 → 分
        cycles.append({
            "start_step": start,
            "end_step": end,
            "duration_min": round(duration_min, 1),
        })

    durations = [c["duration_min"] for c in cycles]
    total_sleep_min = sum(durations)
    total_sim_min = len(state.ve_log) * 5.0 / 60

    return {
        "sleep_count": len(cycles),
        "cycles": cycles,
        "total_sleep_min": round(total_sleep_min, 1),
        "avg_duration_min": round(np.mean(durations), 1) if durations else 0,
        "sleep_pct": round(total_sleep_min / total_sim_min * 100, 1) if total_sim_min > 0 else 0,
    }


def run_v3_simulation():
    """v3パラメータでの24時間シミュレーション"""
    print("Phase 0データを読み込み中...")
    data = load_phase0_data()
    print(f"  {len(data)} レコード読み込み完了")

    # v3パラメータ
    state = SimState(
        rest_ve_recovery_rate=0.008,   # v2: 0.005 → v3: 0.008
        rest_bmc_fraction=0.7,         # v3追加
        sleep_fatigue_recovery_rate=0.010,  # 検証済み
    )

    print("\nv3シミュレーション実行中（24時間分）...")
    steps_24h = min(len(data) - 1, 17280)  # 24h = 17280 steps
    state = run_simulation(data, state, max_steps=steps_24h)
    print(f"  {state.step_count} ステップ完了")

    return state


def run_v2_baseline():
    """v2パラメータでの比較用シミュレーション"""
    data = load_phase0_data()

    state = SimState(
        rest_ve_recovery_rate=0.005,   # v2の値
        rest_bmc_fraction=1.0,         # v2ではBMC軽減なし
        sleep_fatigue_recovery_rate=0.010,
    )

    print("v2ベースラインシミュレーション実行中...")
    steps_24h = min(len(data) - 1, 17280)
    state = run_simulation(data, state, max_steps=steps_24h)
    print(f"  {state.step_count} ステップ完了")

    return state


def plot_comparison(v2_state, v3_state, output_dir):
    """v2 vs v3 の比較チャートを作成する。"""
    fig, axes = plt.subplots(3, 2, figsize=(16, 14))
    fig.suptitle("Seed0 v2 vs v3 シミュレーション比較", fontsize=16, fontweight="bold")

    hours_v2 = np.arange(len(v2_state.ve_log)) * 5 / 3600
    hours_v3 = np.arange(len(v3_state.ve_log)) * 5 / 3600

    # 1. VE推移
    ax = axes[0, 0]
    ax.plot(hours_v2, v2_state.ve_log, alpha=0.5, label="v2", color="red", linewidth=0.5)
    ax.plot(hours_v3, v3_state.ve_log, alpha=0.7, label="v3", color="blue", linewidth=0.5)
    ax.set_title("VE推移")
    ax.set_ylabel("VE")
    ax.set_xlabel("時間 (h)")
    ax.legend()
    ax.axhline(y=0, color="black", linestyle="--", alpha=0.3)
    ax.set_ylim(-5, 105)

    # 2. 覚醒中VEのヒストグラム
    ax = axes[0, 1]
    awake_ve_v2 = [v2_state.ve_log[i] for i in range(len(v2_state.ve_log))
                   if i < len(v2_state.action_log) and v2_state.action_log[i] != "sleeping"]
    awake_ve_v3 = [v3_state.ve_log[i] for i in range(len(v3_state.ve_log))
                   if i < len(v3_state.action_log) and v3_state.action_log[i] != "sleeping"]
    ax.hist(awake_ve_v2, bins=50, alpha=0.5, label="v2", color="red", density=True)
    ax.hist(awake_ve_v3, bins=50, alpha=0.5, label="v3", color="blue", density=True)
    ax.set_title("覚醒中VE分布")
    ax.set_xlabel("VE")
    ax.set_ylabel("密度")
    ax.legend()

    # 3. 疲労推移
    ax = axes[1, 0]
    ax.plot(hours_v2, v2_state.fatigue_log, alpha=0.5, label="v2", color="red", linewidth=0.5)
    ax.plot(hours_v3, v3_state.fatigue_log, alpha=0.7, label="v3", color="blue", linewidth=0.5)
    ax.set_title("疲労推移")
    ax.set_ylabel("疲労")
    ax.set_xlabel("時間 (h)")
    ax.legend()

    # 4. 行動分布比較
    ax = axes[1, 1]
    v2_actions = analyze_actions(v2_state)
    v3_actions = analyze_actions(v3_state)
    action_names = sorted(set(list(v2_actions["awake_counts"].keys()) +
                             list(v3_actions["awake_counts"].keys())))
    action_names = [a for a in action_names if a not in ("sleeping", "none", "blocked")]
    v2_pcts = [v2_actions["awake_counts"].get(a, 0) / max(v2_actions["awake_total"], 1) * 100
               for a in action_names]
    v3_pcts = [v3_actions["awake_counts"].get(a, 0) / max(v3_actions["awake_total"], 1) * 100
               for a in action_names]
    x = np.arange(len(action_names))
    width = 0.35
    ax.bar(x - width/2, v2_pcts, width, label="v2", color="red", alpha=0.7)
    ax.bar(x + width/2, v3_pcts, width, label="v3", color="blue", alpha=0.7)
    ax.set_title("覚醒中の行動分布 (%)")
    ax.set_xticks(x)
    ax.set_xticklabels(action_names, rotation=45, ha="right", fontsize=8)
    ax.legend()

    # 5. 記憶件数推移
    ax = axes[2, 0]
    ax.plot(hours_v2, v2_state.memory_count_log, alpha=0.5, label="v2", color="red", linewidth=0.5)
    ax.plot(hours_v3, v3_state.memory_count_log, alpha=0.7, label="v3", color="blue", linewidth=0.5)
    ax.set_title("記憶件数推移")
    ax.set_ylabel("件数")
    ax.set_xlabel("時間 (h)")
    ax.legend()

    # 6. 指標サマリーテーブル
    ax = axes[2, 1]
    ax.axis("off")

    v2_awake = analyze_awake_ve(v2_state)
    v3_awake = analyze_awake_ve(v3_state)
    v2_sleep = analyze_sleep_cycles(v2_state)
    v3_sleep = analyze_sleep_cycles(v3_state)

    table_data = [
        ["指標", "v2", "v3", "目標"],
        ["覚醒中VE=0 (%)", f"{v2_awake['awake_ve_zero_pct']:.1f}%",
         f"{v3_awake['awake_ve_zero_pct']:.1f}%", "0%"],
        ["覚醒中平均VE", f"{v2_awake['awake_ve_mean']:.1f}",
         f"{v3_awake['awake_ve_mean']:.1f}", "≥10"],
        ["覚醒中VE中央値", f"{v2_awake.get('awake_ve_median', 0):.1f}",
         f"{v3_awake.get('awake_ve_median', 0):.1f}", "—"],
        ["rest選択率", f"{v2_actions['rest_pct']:.1f}%",
         f"{v3_actions['rest_pct']:.1f}%", "~80%"],
        ["睡眠回数", str(v2_sleep["sleep_count"]),
         str(v3_sleep["sleep_count"]), "—"],
        ["睡眠合計 (min)", str(v2_sleep["total_sleep_min"]),
         str(v3_sleep["total_sleep_min"]), "~144min"],
        ["睡眠割合", f"{v2_sleep['sleep_pct']}%",
         f"{v3_sleep['sleep_pct']}%", "~20%"],
    ]

    table = ax.table(cellText=table_data, loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.0, 1.5)
    # ヘッダー行の色
    for j in range(4):
        table[0, j].set_facecolor("#4472C4")
        table[0, j].set_text_props(color="white", fontweight="bold")
    # v3の覚醒中VE=0のセルを強調
    if v3_awake["awake_ve_zero_pct"] < 1.0:
        table[1, 2].set_facecolor("#C6EFCE")  # 緑（達成）
    else:
        table[1, 2].set_facecolor("#FFC7CE")  # 赤（未達成）

    plt.tight_layout()
    path = os.path.join(output_dir, "v3_comparison.png")
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"\n比較チャート保存: {path}")


def main():
    output_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(output_dir, exist_ok=True)

    # v3シミュレーション
    v3_state = run_v3_simulation()

    # v2ベースライン
    v2_state = run_v2_baseline()

    # 分析
    print("\n" + "=" * 60)
    print("  v3 シミュレーション結果")
    print("=" * 60)

    v3_awake = analyze_awake_ve(v3_state)
    v3_actions = analyze_actions(v3_state)
    v3_sleep = analyze_sleep_cycles(v3_state)

    print(f"\n--- 覚醒中VE統計 ---")
    print(f"  覚醒中VE=0割合:   {v3_awake['awake_ve_zero_pct']:.1f}%  {'✅' if v3_awake['awake_ve_zero_pct'] < 1 else '❌'} (目標: 0%)")
    print(f"  覚醒中平均VE:     {v3_awake['awake_ve_mean']:.1f}  {'✅' if v3_awake['awake_ve_mean'] >= 10 else '❌'} (目標: ≥10)")
    print(f"  覚醒中VE中央値:   {v3_awake.get('awake_ve_median', 0):.1f}")
    print(f"  覚醒中VE最低値:   {v3_awake.get('awake_ve_min', 0):.1f}")
    print(f"  覚醒中VE最高値:   {v3_awake.get('awake_ve_max', 0):.1f}")

    print(f"\n--- 行動分布（覚醒中）---")
    for action, count in sorted(v3_actions["awake_counts"].items(), key=lambda x: -x[1]):
        if action in ("sleeping", "none"):
            continue
        pct = count / v3_actions["awake_total"] * 100
        print(f"  {action:<20s}: {count:>5} ({pct:5.1f}%)")
    print(f"  rest選択率: {v3_actions['rest_pct']:.1f}%  {'✅' if 60 < v3_actions['rest_pct'] < 95 else '⚠️'} (目標: ~80%)")

    print(f"\n--- 睡眠サイクル ---")
    print(f"  睡眠回数:   {v3_sleep['sleep_count']}")
    print(f"  睡眠合計:   {v3_sleep['total_sleep_min']} 分")
    print(f"  睡眠割合:   {v3_sleep['sleep_pct']}%")
    if v3_sleep["cycles"]:
        print(f"  平均睡眠時間: {v3_sleep['avg_duration_min']} 分")
        for i, c in enumerate(v3_sleep["cycles"]):
            print(f"    #{i+1}: step {c['start_step']}→{c['end_step']} ({c['duration_min']}分)")

    # v2との比較
    v2_awake = analyze_awake_ve(v2_state)
    v2_actions = analyze_actions(v2_state)
    v2_sleep = analyze_sleep_cycles(v2_state)

    print(f"\n--- v2 → v3 比較 ---")
    print(f"  覚醒中VE=0:  {v2_awake['awake_ve_zero_pct']:.1f}% → {v3_awake['awake_ve_zero_pct']:.1f}%")
    print(f"  覚醒中平均VE: {v2_awake['awake_ve_mean']:.1f} → {v3_awake['awake_ve_mean']:.1f}")
    print(f"  rest選択率:   {v2_actions['rest_pct']:.1f}% → {v3_actions['rest_pct']:.1f}%")
    print(f"  睡眠回数:     {v2_sleep['sleep_count']} → {v3_sleep['sleep_count']}")
    print(f"  睡眠割合:     {v2_sleep['sleep_pct']}% → {v3_sleep['sleep_pct']}%")

    # チャート作成
    plot_comparison(v2_state, v3_state, output_dir)

    # 結果をJSON保存
    results = {
        "v3": {
            "awake_ve": v3_awake,
            "actions": {k: v for k, v in v3_actions.items() if k != "counts"},
            "sleep": {k: v for k, v in v3_sleep.items() if k != "cycles"},
        },
        "v2": {
            "awake_ve": v2_awake,
            "actions": {k: v for k, v in v2_actions.items() if k != "counts"},
            "sleep": {k: v for k, v in v2_sleep.items() if k != "cycles"},
        },
        "parameters": {
            "v3": {"rest_ve_recovery_rate": 0.008, "rest_bmc_fraction": 0.7},
            "v2": {"rest_ve_recovery_rate": 0.005, "rest_bmc_fraction": 1.0},
        }
    }
    results_path = os.path.join(output_dir, "results_v3.json")
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n結果JSON保存: {results_path}")


if __name__ == "__main__":
    main()
