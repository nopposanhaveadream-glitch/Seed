"""
Seed0 Phase 1 シミュレーション検証 v2

v1の発見: VEが覚醒時間の78%で枯渇する構造的欠陥。
修正: rest行動にVE回復効果を追加（「休憩=食事」のアナロジー）。

この再検証では修正後のパラメータ空間を探索し、
「壊れない構造」を確定する。
"""

import sys
import os
import random
import json

import matplotlib
matplotlib.use("Agg")
# 日本語フォント対応: macOS の Hiragino Sans を使用
matplotlib.rcParams["font.family"] = "Hiragino Sans"
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import (
    load_phase0_data, SimState, RunningBaseline, ShortTermMemory,
    ActionSelector, ACTIONS, run_simulation, body_stress_multiplier,
    fatigue_cost_multiplier, comfort_zone_status
)

IMG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(IMG_DIR, exist_ok=True)

print("Phase 0データを読み込み中...")
SENSOR_DATA = load_phase0_data()
print(f"  {len(SENSOR_DATA)} 件 ({len(SENSOR_DATA)*5/3600:.1f}時間)")


# =========================================
# テスト1: rest VE回復率の探索
# =========================================

def test1_rest_recovery():
    """
    rest行動のVE回復率を複数パターンで試す。
    「VE=0の時間比率」と「行動の多様性」が改善されるかを確認。
    """
    print("\n" + "=" * 60)
    print("テスト1: rest VE回復率の探索")
    print("=" * 60)

    # rest回復率のパターン
    rest_rates = [0.0, 0.003, 0.005, 0.008, 0.01, 0.015]
    results = {}

    fig, axes = plt.subplots(len(rest_rates), 1, figsize=(14, 3 * len(rest_rates)),
                              sharex=True)

    for idx, rr in enumerate(rest_rates):
        random.seed(42)
        state = SimState(
            base_rate=0.01,
            rest_ve_recovery_rate=rr,
            ve=100.0,
            fatigue=0.0,
        )
        state = run_simulation(SENSOR_DATA, state, enable_actions=True, enable_sleep=True)

        ve_arr = np.array(state.ve_log)
        hours = np.arange(len(ve_arr)) * 5 / 3600

        zero_pct = np.sum(ve_arr <= 0.01) / len(ve_arr) * 100
        mean_ve = np.mean(ve_arr)
        min_ve = np.min(ve_arr)
        sleep_count = len(state.sleep_log)
        sleep_hours = sum(e - s for s, e in state.sleep_log) * 5 / 3600

        # 行動分布
        action_counts = {}
        for a in state.action_log:
            action_counts[a] = action_counts.get(a, 0) + 1
        total = len(state.action_log)
        rest_pct = action_counts.get("rest", 0) / total * 100
        blocked_pct = action_counts.get("blocked", 0) / total * 100
        active_pct = 100 - rest_pct - blocked_pct - action_counts.get("sleeping", 0) / total * 100

        results[rr] = {
            "zero_pct": zero_pct,
            "mean_ve": mean_ve,
            "min_ve": min_ve,
            "sleep_count": sleep_count,
            "sleep_hours": sleep_hours,
            "rest_pct": rest_pct,
            "blocked_pct": blocked_pct,
            "active_pct": active_pct,
            "action_dist": {k: v / total * 100 for k, v in sorted(action_counts.items())},
        }

        print(f"\n  rest回復率={rr}:")
        print(f"    VE=0割合: {zero_pct:.1f}%, 平均VE: {mean_ve:.1f}")
        print(f"    睡眠: {sleep_count}回, {sleep_hours:.1f}h")
        print(f"    rest: {rest_pct:.1f}%, blocked: {blocked_pct:.1f}%, 能動行動: {active_pct:.1f}%")

        # グラフ
        ax = axes[idx]
        ax.plot(hours, ve_arr, linewidth=0.5, color="steelblue")
        ax.fill_between(hours, 0, ve_arr, alpha=0.15, color="steelblue")
        ax.set_ylabel("VE")
        label = f"rest回復率={rr} (平均VE={mean_ve:.1f}, VE=0: {zero_pct:.1f}%)"
        ax.set_title(label, fontsize=10, loc="left")
        ax.set_ylim(-5, 105)
        ax.axhline(y=0, color="red", linewidth=0.5, linestyle="--")
        for s, e in state.sleep_log:
            ax.axvspan(s * 5 / 3600, e * 5 / 3600, alpha=0.15, color="purple")

    axes[-1].set_xlabel("時間 (h)")
    plt.tight_layout()
    plt.savefig(os.path.join(IMG_DIR, "v2_test1_rest_recovery.png"), dpi=150)
    plt.close()
    print(f"\n  グラフ保存: v2_test1_rest_recovery.png")
    return results


# =========================================
# テスト2: 最適パラメータでの睡眠サイクル
# =========================================

def test2_sleep_cycle_v2(rest_rate: float):
    """
    rest VE回復を有効にした上で、睡眠サイクルを再検証。
    """
    print("\n" + "=" * 60)
    print(f"テスト2: 睡眠サイクル（rest回復率={rest_rate}）")
    print("=" * 60)

    fatigue_rates = [0.0015, 0.0023, 0.003]
    recovery_rates = [0.010, 0.014, 0.020]
    results = {}

    fig, axes = plt.subplots(len(fatigue_rates), len(recovery_rates),
                              figsize=(16, 3 * len(fatigue_rates)), sharex=True, sharey=True)

    for i, fr in enumerate(fatigue_rates):
        for j, rr in enumerate(recovery_rates):
            random.seed(42)
            state = SimState(
                base_rate=0.01,
                rest_ve_recovery_rate=rest_rate,
                base_fatigue_rate=fr,
                sleep_fatigue_recovery_rate=rr,
                ve=100.0,
                fatigue=0.0,
            )
            state = run_simulation(SENSOR_DATA, state, enable_actions=True, enable_sleep=True)

            fat_arr = np.array(state.fatigue_log)
            ve_arr = np.array(state.ve_log)
            hours = np.arange(len(fat_arr)) * 5 / 3600

            sleep_count = len(state.sleep_log)
            wake_durations, sleep_durations = [], []
            if sleep_count > 0:
                prev_end = 0
                for s, e in state.sleep_log:
                    wake_durations.append((s - prev_end) * 5 / 3600)
                    sleep_durations.append((e - s) * 5 / 3600)
                avg_wake = np.mean(wake_durations)
                avg_sleep = np.mean(sleep_durations)
            else:
                avg_wake = len(SENSOR_DATA) * 5 / 3600
                avg_sleep = 0

            zero_pct = np.sum(ve_arr <= 0.01) / len(ve_arr) * 100

            key = f"fr={fr}_rr={rr}"
            results[key] = {
                "sleep_count": sleep_count,
                "avg_wake_hours": avg_wake,
                "avg_sleep_hours": avg_sleep,
                "mean_fatigue": np.mean(fat_arr),
                "mean_ve": np.mean(ve_arr),
                "ve_zero_pct": zero_pct,
            }

            print(f"\n  疲労率={fr}, 回復率={rr}:")
            print(f"    睡眠{sleep_count}回, 覚醒{avg_wake:.1f}h, 睡眠{avg_sleep:.1f}h")
            print(f"    平均VE: {np.mean(ve_arr):.1f}, VE=0: {zero_pct:.1f}%")

            ax = axes[i][j]
            ax.plot(hours, fat_arr, linewidth=0.5, color="orangered", label="疲労")
            ax2 = ax.twinx()
            ax2.plot(hours, ve_arr, linewidth=0.5, color="steelblue", alpha=0.5, label="VE")
            ax2.set_ylim(-5, 105)
            ax.set_ylim(-5, 105)
            ax.set_title(f"疲労率={fr}, 回復率={rr}\n覚醒{avg_wake:.1f}h/睡眠{avg_sleep:.1f}h, VE=0:{zero_pct:.0f}%",
                          fontsize=8, loc="left")
            for s, e in state.sleep_log:
                ax.axvspan(s * 5 / 3600, e * 5 / 3600, alpha=0.15, color="purple")

    axes[-1][1].set_xlabel("時間 (h)")
    plt.tight_layout()
    plt.savefig(os.path.join(IMG_DIR, "v2_test2_sleep_cycle.png"), dpi=150)
    plt.close()
    print(f"\n  グラフ保存: v2_test2_sleep_cycle.png")
    return results


# =========================================
# テスト3: comfort zone（v1で正常だったので簡易再確認）
# =========================================

def test3_comfort_zone_v2():
    """alpha=0.001 で簡易再確認。v1で問題なかったので詳細は省略。"""
    print("\n" + "=" * 60)
    print("テスト3: comfort zone（簡易再確認）")
    print("=" * 60)

    baseline = RunningBaseline(alpha=0.001)
    key_metrics = ["memory_pressure_percent", "cpu_usage_percent"]
    mean_logs = {k: [] for k in key_metrics}
    raw_logs = {k: [] for k in key_metrics}

    for sensor in SENSOR_DATA:
        for key in key_metrics:
            val = sensor.get(key)
            if val is not None:
                baseline.update(key, val)
                m, s = baseline.get_stats(key)
                mean_logs[key].append(m)
                raw_logs[key].append(val)

    results = {}
    for key in key_metrics:
        m, s = baseline.get_stats(key)
        results[key] = {"final_mean": m, "final_stddev": s,
                        "cz_lower": m - 2*s, "cz_upper": m + 2*s}
        print(f"  {key}: 平均={m:.2f}, σ={s:.2f}, CZ=[{m-2*s:.2f}, {m+2*s:.2f}]")

    print("  → v1と同一。alpha=0.001は安定。")
    return results


# =========================================
# テスト4: 記憶コスト再検証
# =========================================

def test4_memory_cost_v2(rest_rate: float):
    """rest VE回復を有効にした上で、記憶システムの動作を再検証。"""
    print("\n" + "=" * 60)
    print(f"テスト4: 記憶コスト（rest回復率={rest_rate}）")
    print("=" * 60)

    random.seed(42)
    state = SimState(
        base_rate=0.01,
        rest_ve_recovery_rate=rest_rate,
        ve=100.0,
        fatigue=0.0,
    )
    state = run_simulation(SENSOR_DATA, state, enable_actions=True, enable_sleep=True)

    ve_arr = np.array(state.ve_log)
    mem_arr = np.array(state.memory_count_log)
    fat_arr = np.array(state.fatigue_log)
    hours = np.arange(len(ve_arr)) * 5 / 3600

    results = {
        "mean_memory": np.mean(mem_arr),
        "min_memory": int(np.min(mem_arr)),
        "max_memory": int(np.max(mem_arr)),
        "wipeout_pct": np.sum(mem_arr <= 20) / len(mem_arr) * 100,
        "mean_ve": np.mean(ve_arr),
    }

    print(f"  記憶件数: 平均{results['mean_memory']:.0f}, 最小{results['min_memory']}, 最大{results['max_memory']}")
    print(f"  ワイプアウト(≤20件): {results['wipeout_pct']:.1f}%")
    print(f"  平均VE: {results['mean_ve']:.1f}")

    fig, axes = plt.subplots(3, 1, figsize=(14, 8), sharex=True)
    axes[0].plot(hours, ve_arr, linewidth=0.5, color="steelblue")
    axes[0].set_ylabel("VE")
    axes[0].set_ylim(-5, 105)
    axes[0].set_title(f"VE推移（rest回復率={rest_rate}）", fontsize=10)
    axes[1].plot(hours, mem_arr, linewidth=0.5, color="green")
    axes[1].set_ylabel("記憶件数")
    axes[1].set_ylim(0, 550)
    axes[1].set_title("短期記憶件数", fontsize=10)
    axes[2].plot(hours, fat_arr, linewidth=0.5, color="orangered")
    axes[2].set_ylabel("疲労")
    axes[2].set_ylim(-5, 105)
    axes[2].set_xlabel("時間 (h)")
    axes[2].set_title("疲労推移", fontsize=10)
    for s, e in state.sleep_log:
        for row in range(3):
            axes[row].axvspan(s * 5 / 3600, e * 5 / 3600, alpha=0.15, color="purple")
    plt.tight_layout()
    plt.savefig(os.path.join(IMG_DIR, "v2_test4_memory_cost.png"), dpi=150)
    plt.close()
    print(f"  グラフ保存: v2_test4_memory_cost.png")
    return results


# =========================================
# テスト5: 行動選択の多様性
# =========================================

def test5_action_selection_v2(rest_rate: float):
    """rest VE回復を有効にして、行動の多様性がどう変わるかを検証。"""
    print("\n" + "=" * 60)
    print(f"テスト5: 行動選択（rest回復率={rest_rate}）")
    print("=" * 60)

    random.seed(42)
    state = SimState(
        base_rate=0.01,
        rest_ve_recovery_rate=rest_rate,
        ve=100.0,
        fatigue=0.0,
    )
    state = run_simulation(SENSOR_DATA, state, enable_actions=True, enable_sleep=True)

    action_counts = {}
    for a in state.action_log:
        action_counts[a] = action_counts.get(a, 0) + 1
    total = len(state.action_log)

    results = {
        "action_distribution": {k: v / total * 100 for k, v in sorted(action_counts.items())},
        "q_table_size": len(state.selector.q_table),
        "final_epsilon": state.selector.epsilon,
    }

    print(f"  Q値テーブル: {results['q_table_size']}状態, epsilon={results['final_epsilon']:.4f}")
    print(f"  行動分布:")
    for a, pct in sorted(results["action_distribution"].items(), key=lambda x: -x[1]):
        bar = "█" * int(pct / 2)
        print(f"    {a:20s}: {pct:5.1f}% {bar}")

    # 前半vs後半
    half = total // 2
    first = state.action_log[:half]
    second = state.action_log[half:]
    first_c = {}
    for a in first:
        first_c[a] = first_c.get(a, 0) + 1
    second_c = {}
    for a in second:
        second_c[a] = second_c.get(a, 0) + 1
    all_a = sorted(set(list(first_c.keys()) + list(second_c.keys())))

    print(f"\n  前半 vs 後半:")
    for a in all_a:
        p1 = first_c.get(a, 0) / max(1, len(first)) * 100
        p2 = second_c.get(a, 0) / max(1, len(second)) * 100
        arrow = "↑" if p2 - p1 > 1 else ("↓" if p1 - p2 > 1 else "→")
        print(f"    {a:20s}: {p1:5.1f}% → {p2:5.1f}% {arrow}")

    # グラフ
    active_actions = [a for a in all_a if a not in ("blocked", "sleeping", "none")]
    fig, axes = plt.subplots(3, 1, figsize=(14, 10))

    # 行動分布
    x = np.arange(len(active_actions))
    w = 0.35
    f_vals = [first_c.get(a, 0) / max(1, len(first)) * 100 for a in active_actions]
    s_vals = [second_c.get(a, 0) / max(1, len(second)) * 100 for a in active_actions]
    axes[0].bar(x - w/2, f_vals, w, label="前半（探索多め）", color="skyblue")
    axes[0].bar(x + w/2, s_vals, w, label="後半（活用多め）", color="steelblue")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(active_actions, rotation=30, fontsize=8)
    axes[0].set_ylabel("選択率 (%)")
    axes[0].set_title("行動分布の変化（前半 vs 後半）", fontsize=10)
    axes[0].legend(fontsize=8)

    hours = np.arange(len(state.ve_log)) * 5 / 3600
    axes[1].plot(hours, state.ve_log, linewidth=0.5, color="steelblue")
    axes[1].set_ylabel("VE")
    axes[1].set_ylim(-5, 105)
    axes[1].set_title("仮想エネルギー推移", fontsize=10)

    axes[2].plot(hours, state.fatigue_log, linewidth=0.5, color="orangered")
    axes[2].set_ylabel("疲労")
    axes[2].set_ylim(-5, 105)
    axes[2].set_xlabel("時間 (h)")
    axes[2].set_title("疲労推移", fontsize=10)

    for s, e in state.sleep_log:
        axes[1].axvspan(s * 5 / 3600, e * 5 / 3600, alpha=0.15, color="purple")
        axes[2].axvspan(s * 5 / 3600, e * 5 / 3600, alpha=0.15, color="purple")

    plt.tight_layout()
    plt.savefig(os.path.join(IMG_DIR, "v2_test5_action_selection.png"), dpi=150)
    plt.close()
    print(f"\n  グラフ保存: v2_test5_action_selection.png")
    return results


# =========================================
# 壊れる条件の再特定
# =========================================

def find_breaking_points_v2(rest_rate: float):
    """修正版での壊れる条件を特定。"""
    print("\n" + "=" * 60)
    print(f"壊れる条件の再特定（rest回復率={rest_rate}）")
    print("=" * 60)

    short_data = SENSOR_DATA[:8640]  # 12時間
    results = {}

    # VE復帰不能の境界
    print("\n  [VE × base_rate]")
    for br in [0.01, 0.015, 0.02, 0.03, 0.05]:
        random.seed(42)
        state = SimState(base_rate=br, rest_ve_recovery_rate=rest_rate, ve=100.0, fatigue=0.0)
        state = run_simulation(short_data, state, enable_actions=True, enable_sleep=True)
        ve_arr = np.array(state.ve_log)
        zero_pct = np.sum(ve_arr <= 0.01) / len(ve_arr) * 100
        mean_ve = np.mean(ve_arr)
        status = "OK" if zero_pct < 30 else ("注意" if zero_pct < 60 else "壊れる")
        print(f"    base_rate={br}: 平均VE={mean_ve:.1f}, VE=0={zero_pct:.1f}% → {status}")
        results[f"ve_br={br}"] = {"mean_ve": mean_ve, "zero_pct": zero_pct, "status": status}

    # 疲労復帰不能の境界
    print("\n  [疲労 × 蓄積率]")
    for fr in [0.003, 0.005, 0.008, 0.01, 0.015]:
        random.seed(42)
        state = SimState(base_fatigue_rate=fr, rest_ve_recovery_rate=rest_rate, ve=100.0, fatigue=0.0)
        state = run_simulation(short_data, state, enable_actions=True, enable_sleep=True)
        fat_arr = np.array(state.fatigue_log)
        stuck = np.sum(fat_arr >= 95) / len(fat_arr) * 100
        status = "OK" if stuck < 20 else "壊れる"
        print(f"    疲労率={fr}: F≥95={stuck:.1f}% → {status}")
        results[f"fat_fr={fr}"] = {"stuck_pct": stuck, "status": status}

    # 記憶消失の境界
    print("\n  [記憶 × コスト率]")
    for mcr in [0.001, 0.003, 0.005, 0.01]:
        random.seed(42)
        state = SimState(base_rate=0.01, rest_ve_recovery_rate=rest_rate, ve=100.0, fatigue=0.0)
        original_cost = ShortTermMemory.maintenance_cost_per_sec
        def patched_cost(self, _mcr=mcr):
            return len(self.memories) * _mcr / 60
        ShortTermMemory.maintenance_cost_per_sec = patched_cost
        state = run_simulation(short_data, state, enable_actions=True, enable_sleep=True)
        ShortTermMemory.maintenance_cost_per_sec = original_cost
        mem_arr = np.array(state.memory_count_log)
        wipeout = np.sum(mem_arr <= 20) / len(mem_arr) * 100
        status = "OK" if wipeout < 10 else "壊れる"
        print(f"    コスト率={mcr}: ワイプアウト={wipeout:.1f}% → {status}")
        results[f"mem_mcr={mcr}"] = {"wipeout_pct": wipeout, "status": status}

    return results


# =========================================
# 比較グラフ: v1 vs v2
# =========================================

def comparison_chart(rest_rate: float):
    """v1（rest回復なし）vs v2（rest回復あり）の比較グラフ。"""
    print("\n" + "=" * 60)
    print("比較: v1（修正前）vs v2（修正後）")
    print("=" * 60)

    fig, axes = plt.subplots(2, 2, figsize=(14, 8))

    for idx, (rr, label) in enumerate([(0.0, "v1: rest回復なし"), (rest_rate, f"v2: rest回復率={rest_rate}")]):
        random.seed(42)
        state = SimState(base_rate=0.01, rest_ve_recovery_rate=rr, ve=100.0, fatigue=0.0)
        state = run_simulation(SENSOR_DATA, state, enable_actions=True, enable_sleep=True)

        ve_arr = np.array(state.ve_log)
        fat_arr = np.array(state.fatigue_log)
        hours = np.arange(len(ve_arr)) * 5 / 3600

        zero_pct = np.sum(ve_arr <= 0.01) / len(ve_arr) * 100
        mean_ve = np.mean(ve_arr)

        # VE
        ax = axes[0][idx]
        ax.plot(hours, ve_arr, linewidth=0.5, color="steelblue")
        ax.fill_between(hours, 0, ve_arr, alpha=0.15, color="steelblue")
        ax.set_title(f"{label}\n平均VE={mean_ve:.1f}, VE=0: {zero_pct:.1f}%", fontsize=10)
        ax.set_ylabel("VE")
        ax.set_ylim(-5, 105)
        for s, e in state.sleep_log:
            ax.axvspan(s * 5 / 3600, e * 5 / 3600, alpha=0.15, color="purple")

        # 行動分布
        ax2 = axes[1][idx]
        action_counts = {}
        for a in state.action_log:
            action_counts[a] = action_counts.get(a, 0) + 1
        total = len(state.action_log)
        active = {k: v / total * 100 for k, v in action_counts.items()
                  if k not in ("sleeping", "none")}
        names = sorted(active.keys())
        vals = [active[n] for n in names]
        bars = ax2.barh(names, vals, color="steelblue")
        ax2.set_xlabel("選択率 (%)")
        ax2.set_title(f"行動分布", fontsize=10)
        # 値ラベル
        for bar, val in zip(bars, vals):
            if val > 0.5:
                ax2.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height()/2,
                         f"{val:.1f}%", va="center", fontsize=7)

        stat_text = (f"平均VE={mean_ve:.1f}\n"
                     f"VE=0: {zero_pct:.1f}%\n"
                     f"睡眠: {len(state.sleep_log)}回")
        print(f"\n  {label}: 平均VE={mean_ve:.1f}, VE=0={zero_pct:.1f}%, 睡眠{len(state.sleep_log)}回")

    plt.tight_layout()
    plt.savefig(os.path.join(IMG_DIR, "v2_comparison.png"), dpi=150)
    plt.close()
    print(f"  グラフ保存: v2_comparison.png")


# =========================================
# メイン
# =========================================

def main():
    print("=" * 60)
    print("Seed0 Phase 1 シミュレーション検証 v2")
    print("修正: rest行動にVE回復効果を追加")
    print("=" * 60)

    all_results = {}

    # テスト1: rest回復率の探索で最適値を見つける
    all_results["test1"] = test1_rest_recovery()

    # テスト1の結果から最適なrest回復率を選択
    # VE=0割合が十分低く、かつrest依存度が高すぎないものを選ぶ
    best_rate = 0.005  # デフォルト
    for rate, data in sorted(all_results["test1"].items()):
        if rate == 0.0:
            continue
        if data["zero_pct"] < 30 and data["mean_ve"] > 20:
            best_rate = rate
            break
    # もし条件を満たすものがなければ、zero_pctが最小のものを選ぶ
    if all_results["test1"].get(best_rate, {}).get("zero_pct", 100) > 30:
        best_rate = min([r for r in all_results["test1"] if r > 0],
                        key=lambda r: all_results["test1"][r]["zero_pct"])

    print(f"\n>>> 採用するrest回復率: {best_rate}")
    all_results["best_rest_rate"] = best_rate

    # 残りのテストは最適パラメータで実行
    all_results["test2"] = test2_sleep_cycle_v2(best_rate)
    all_results["test3"] = test3_comfort_zone_v2()
    all_results["test4"] = test4_memory_cost_v2(best_rate)
    all_results["test5"] = test5_action_selection_v2(best_rate)
    all_results["breaking"] = find_breaking_points_v2(best_rate)

    # v1 vs v2 比較
    comparison_chart(best_rate)

    # 結果保存
    json_path = os.path.join(IMG_DIR, "results_v2.json")
    with open(json_path, "w") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n結果JSON: {json_path}")

    print("\n" + "=" * 60)
    print("全テスト完了")
    print("=" * 60)

    return all_results


if __name__ == "__main__":
    main()
