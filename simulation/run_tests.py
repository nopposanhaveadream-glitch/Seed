"""
Seed0 Phase 1 シミュレーション検証

5つのテストを実行し、結果をグラフと数値でまとめる。
目的: 「壊れない構造」を見つけること（原則9）
"""

import sys
import os
import random
import json

# matplotlib の非表示バックエンド設定（画面なしでグラフ保存）
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import (
    load_phase0_data, SimState, RunningBaseline, ShortTermMemory,
    ActionSelector, ACTIONS, run_simulation, body_stress_multiplier,
    fatigue_cost_multiplier, comfort_zone_status
)

# 出力ディレクトリ
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs")
IMG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(IMG_DIR, exist_ok=True)

# Phase 0 データをロード
print("Phase 0データを読み込み中...")
SENSOR_DATA = load_phase0_data()
print(f"  {len(SENSOR_DATA)} 件のレコードを読み込みました")
TOTAL_SECONDS = len(SENSOR_DATA) * 5
TOTAL_HOURS = TOTAL_SECONDS / 3600
print(f"  総時間: {TOTAL_HOURS:.1f} 時間")


# =========================================
# テスト1: VE枯渇テスト
# =========================================

def test1_ve_depletion():
    """
    base_rate を5パターンで試し、VEが0になるまでの時間と
    rest/sleepによる回復で持続可能かを確認する。
    """
    print("\n" + "=" * 60)
    print("テスト1: VE枯渇テスト")
    print("=" * 60)

    base_rates = [0.005, 0.008, 0.01, 0.012, 0.015]
    results = {}

    fig, axes = plt.subplots(len(base_rates), 1, figsize=(14, 3 * len(base_rates)),
                              sharex=True)

    for idx, br in enumerate(base_rates):
        random.seed(42)
        state = SimState(
            base_rate=br,
            ve=100.0,
            fatigue=0.0,
        )
        # 睡眠あり・行動ありでシミュレーション
        state = run_simulation(SENSOR_DATA, state, enable_actions=True, enable_sleep=True)

        ve_arr = np.array(state.ve_log)
        hours = np.arange(len(ve_arr)) * 5 / 3600

        # VEが0になったステップ
        zero_steps = np.where(ve_arr <= 0.01)[0]
        first_zero_hour = hours[zero_steps[0]] if len(zero_steps) > 0 else None
        zero_count = len(zero_steps)
        zero_pct = zero_count / len(ve_arr) * 100
        mean_ve = np.mean(ve_arr)
        min_ve = np.min(ve_arr)

        # 睡眠回数と時間
        sleep_count = len(state.sleep_log)
        sleep_steps = sum(e - s for s, e in state.sleep_log)
        sleep_hours = sleep_steps * 5 / 3600

        results[br] = {
            "first_zero_hour": first_zero_hour,
            "zero_pct": zero_pct,
            "mean_ve": mean_ve,
            "min_ve": min_ve,
            "sleep_count": sleep_count,
            "sleep_hours": sleep_hours,
        }

        print(f"\n  base_rate={br}:")
        print(f"    初回VE=0到達: {f'{first_zero_hour:.2f}時間' if first_zero_hour else 'なし（枯渇せず）'}")
        print(f"    VE=0の時間割合: {zero_pct:.1f}%")
        print(f"    平均VE: {mean_ve:.1f}, 最小VE: {min_ve:.1f}")
        print(f"    睡眠回数: {sleep_count}, 睡眠合計時間: {sleep_hours:.1f}時間")

        # グラフ
        ax = axes[idx]
        ax.plot(hours, ve_arr, linewidth=0.5, color="steelblue")
        ax.fill_between(hours, 0, ve_arr, alpha=0.2, color="steelblue")
        ax.set_ylabel("VE")
        ax.set_title(f"base_rate = {br} (平均VE={mean_ve:.1f}, 睡眠{sleep_count}回)",
                      fontsize=10, loc="left")
        ax.set_ylim(-5, 105)
        ax.axhline(y=0, color="red", linewidth=0.5, linestyle="--")
        # 睡眠期間を塗る
        for s, e in state.sleep_log:
            ax.axvspan(s * 5 / 3600, e * 5 / 3600, alpha=0.15, color="purple")

    axes[-1].set_xlabel("時間 (h)")
    plt.tight_layout()
    plt.savefig(os.path.join(IMG_DIR, "test1_ve_depletion.png"), dpi=150)
    plt.close()
    print(f"\n  グラフ保存: simulation/results/test1_ve_depletion.png")

    return results


# =========================================
# テスト2: 睡眠サイクルテスト
# =========================================

def test2_sleep_cycle():
    """
    疲労蓄積率と回復率の組み合わせで、自然な覚醒/睡眠サイクルが生まれるか。
    """
    print("\n" + "=" * 60)
    print("テスト2: 睡眠サイクルテスト")
    print("=" * 60)

    # パラメータグリッド
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
                base_fatigue_rate=fr,
                sleep_fatigue_recovery_rate=rr,
                ve=100.0,
                fatigue=0.0,
            )
            state = run_simulation(SENSOR_DATA, state, enable_actions=True, enable_sleep=True)

            fat_arr = np.array(state.fatigue_log)
            ve_arr = np.array(state.ve_log)
            hours = np.arange(len(fat_arr)) * 5 / 3600

            # 睡眠統計
            sleep_count = len(state.sleep_log)
            if sleep_count > 0:
                wake_durations = []
                sleep_durations = []
                for s, e in state.sleep_log:
                    sleep_durations.append((e - s) * 5 / 3600)
                # 覚醒時間を計算
                prev_end = 0
                for s, e in state.sleep_log:
                    wake_durations.append((s - prev_end) * 5 / 3600)
                    prev_end = e
                avg_wake = np.mean(wake_durations) if wake_durations else 0
                avg_sleep = np.mean(sleep_durations) if sleep_durations else 0
            else:
                avg_wake = TOTAL_HOURS
                avg_sleep = 0

            key = f"fr={fr}_rr={rr}"
            results[key] = {
                "fatigue_rate": fr,
                "recovery_rate": rr,
                "sleep_count": sleep_count,
                "avg_wake_hours": avg_wake,
                "avg_sleep_hours": avg_sleep,
                "mean_fatigue": np.mean(fat_arr),
                "mean_ve": np.mean(ve_arr),
            }

            print(f"\n  疲労率={fr}, 回復率={rr}:")
            print(f"    睡眠回数: {sleep_count}")
            print(f"    平均覚醒: {avg_wake:.1f}h, 平均睡眠: {avg_sleep:.1f}h")
            print(f"    平均疲労: {np.mean(fat_arr):.1f}, 平均VE: {np.mean(ve_arr):.1f}")

            ax = axes[i][j]
            ax.plot(hours, fat_arr, linewidth=0.5, color="orangered", label="疲労")
            ax2 = ax.twinx()
            ax2.plot(hours, ve_arr, linewidth=0.5, color="steelblue", alpha=0.5, label="VE")
            ax2.set_ylim(-5, 105)
            ax.set_ylim(-5, 105)
            ax.set_title(f"疲労率={fr}, 回復率={rr}\n睡眠{sleep_count}回, 覚醒{avg_wake:.1f}h/睡眠{avg_sleep:.1f}h",
                          fontsize=8, loc="left")
            for s, e in state.sleep_log:
                ax.axvspan(s * 5 / 3600, e * 5 / 3600, alpha=0.15, color="purple")

    axes[-1][1].set_xlabel("時間 (h)")
    plt.tight_layout()
    plt.savefig(os.path.join(IMG_DIR, "test2_sleep_cycle.png"), dpi=150)
    plt.close()
    print(f"\n  グラフ保存: simulation/results/test2_sleep_cycle.png")

    return results


# =========================================
# テスト3: comfort zone 適応テスト
# =========================================

def test3_comfort_zone():
    """
    RunningBaseline に Phase 0 データを流し込んだとき、
    EMA が妥当な範囲に収束するか。
    """
    print("\n" + "=" * 60)
    print("テスト3: comfort zone 適応テスト")
    print("=" * 60)

    alphas = [0.0005, 0.001, 0.005, 0.01]
    key_metrics = ["memory_pressure_percent", "cpu_usage_percent"]
    results = {}

    fig, axes = plt.subplots(len(key_metrics), len(alphas),
                              figsize=(16, 4 * len(key_metrics)), sharex=True)

    for j, alpha in enumerate(alphas):
        baseline = RunningBaseline(alpha=alpha)
        mean_logs = {k: [] for k in key_metrics}
        upper_logs = {k: [] for k in key_metrics}
        lower_logs = {k: [] for k in key_metrics}
        raw_logs = {k: [] for k in key_metrics}

        for sensor in SENSOR_DATA:
            for key in key_metrics:
                val = sensor.get(key)
                if val is not None:
                    baseline.update(key, val)
                    m, s = baseline.get_stats(key)
                    mean_logs[key].append(m)
                    upper_logs[key].append(m + 2 * s)
                    lower_logs[key].append(m - 2 * s)
                    raw_logs[key].append(val)

        results[f"alpha={alpha}"] = {}
        for key in key_metrics:
            final_m, final_s = baseline.get_stats(key)
            results[f"alpha={alpha}"][key] = {
                "final_mean": final_m,
                "final_stddev": final_s,
            }
            print(f"\n  alpha={alpha}, {key}:")
            print(f"    最終平均: {final_m:.2f}, 最終stddev: {final_s:.2f}")
            print(f"    comfort zone: [{final_m - 2*final_s:.2f}, {final_m + 2*final_s:.2f}]")

        for i, key in enumerate(key_metrics):
            ax = axes[i][j]
            n = len(raw_logs[key])
            hours = np.arange(n) * 5 / 3600
            ax.scatter(hours, raw_logs[key], s=0.1, alpha=0.1, color="gray", label="実測値")
            ax.plot(hours, mean_logs[key], linewidth=1, color="red", label="EMA平均")
            ax.fill_between(hours, lower_logs[key], upper_logs[key],
                            alpha=0.2, color="red", label="±2σ")
            ax.set_title(f"alpha={alpha}, {key}", fontsize=9, loc="left")
            if j == 0:
                ax.set_ylabel(key.replace("_", " "))
            if i == 0 and j == 0:
                ax.legend(fontsize=7, loc="upper right")

    axes[-1][1].set_xlabel("時間 (h)")
    plt.tight_layout()
    plt.savefig(os.path.join(IMG_DIR, "test3_comfort_zone.png"), dpi=150)
    plt.close()
    print(f"\n  グラフ保存: simulation/results/test3_comfort_zone.png")

    return results


# =========================================
# テスト4: 記憶コスト均衡テスト
# =========================================

def test4_memory_cost():
    """
    短期記憶500件を維持しつつVEが回復不能にならないか。
    記憶を全て失う前に睡眠で回復できるか。
    """
    print("\n" + "=" * 60)
    print("テスト4: 記憶コスト均衡テスト")
    print("=" * 60)

    # 記憶コスト率を3パターンで試す
    memory_cost_rates = [0.0005, 0.001, 0.002]  # VE/件/分
    results = {}

    fig, axes = plt.subplots(3, len(memory_cost_rates),
                              figsize=(16, 9), sharex=True)

    for j, mcr in enumerate(memory_cost_rates):
        random.seed(42)

        # エンジンの記憶コストをオーバーライドするため、カスタムシミュレーション
        state = SimState(
            base_rate=0.01,
            ve=100.0,
            fatigue=0.0,
        )

        # ShortTermMemoryの維持コストを変更するためパッチ
        original_cost = ShortTermMemory.maintenance_cost_per_sec
        def patched_cost(self, _mcr=mcr):
            return len(self.memories) * _mcr / 60
        ShortTermMemory.maintenance_cost_per_sec = patched_cost

        state = run_simulation(SENSOR_DATA, state, enable_actions=True, enable_sleep=True)

        # 元に戻す
        ShortTermMemory.maintenance_cost_per_sec = original_cost

        ve_arr = np.array(state.ve_log)
        mem_arr = np.array(state.memory_count_log)
        fat_arr = np.array(state.fatigue_log)
        hours = np.arange(len(ve_arr)) * 5 / 3600

        min_mem = int(np.min(mem_arr))
        max_mem = int(np.max(mem_arr))
        mean_mem = np.mean(mem_arr)
        total_wipeouts = sum(1 for m in mem_arr if m <= 20)

        results[f"cost={mcr}"] = {
            "memory_cost_rate": mcr,
            "mean_memory_count": mean_mem,
            "min_memory": min_mem,
            "max_memory": max_mem,
            "wipeout_steps": total_wipeouts,
            "mean_ve": np.mean(ve_arr),
        }

        print(f"\n  記憶コスト率={mcr} VE/件/分:")
        print(f"    記憶件数: 平均{mean_mem:.0f}, 最小{min_mem}, 最大{max_mem}")
        print(f"    記憶ワイプアウト（≤20件）: {total_wipeouts}ステップ")
        print(f"    平均VE: {np.mean(ve_arr):.1f}")

        # VE
        axes[0][j].plot(hours, ve_arr, linewidth=0.5, color="steelblue")
        axes[0][j].set_title(f"コスト={mcr} VE/件/分", fontsize=9, loc="left")
        axes[0][j].set_ylabel("VE")
        axes[0][j].set_ylim(-5, 105)

        # 記憶件数
        axes[1][j].plot(hours, mem_arr, linewidth=0.5, color="green")
        axes[1][j].set_ylabel("記憶件数")
        axes[1][j].set_ylim(0, 550)

        # 疲労
        axes[2][j].plot(hours, fat_arr, linewidth=0.5, color="orangered")
        axes[2][j].set_ylabel("疲労")
        axes[2][j].set_ylim(-5, 105)
        axes[2][j].set_xlabel("時間 (h)")

        # 睡眠期間を全行に塗る
        for s, e in state.sleep_log:
            for row in range(3):
                axes[row][j].axvspan(s * 5 / 3600, e * 5 / 3600, alpha=0.15, color="purple")

    plt.tight_layout()
    plt.savefig(os.path.join(IMG_DIR, "test4_memory_cost.png"), dpi=150)
    plt.close()
    print(f"\n  グラフ保存: simulation/results/test4_memory_cost.png")

    return results


# =========================================
# テスト5: 行動選択の基本動作
# =========================================

def test5_action_selection():
    """
    Q学習がrewardに基づいて学習を進めるか。
    全行動が「rest」だけに収束しないか。
    """
    print("\n" + "=" * 60)
    print("テスト5: 行動選択の基本動作")
    print("=" * 60)

    random.seed(42)
    state = SimState(
        base_rate=0.01,
        ve=100.0,
        fatigue=0.0,
    )
    state = run_simulation(SENSOR_DATA, state, enable_actions=True, enable_sleep=True)

    # 行動の統計
    action_counts = {}
    for a in state.action_log:
        action_counts[a] = action_counts.get(a, 0) + 1

    total = len(state.action_log)
    results = {
        "action_distribution": {k: v / total * 100 for k, v in sorted(action_counts.items())},
        "total_steps": total,
        "q_table_size": len(state.selector.q_table),
        "final_epsilon": state.selector.epsilon,
    }

    print(f"\n  総ステップ: {total}")
    print(f"  Q値テーブルサイズ: {len(state.selector.q_table)}状態")
    print(f"  最終epsilon: {state.selector.epsilon:.4f}")
    print(f"\n  行動分布:")
    for action, pct in sorted(results["action_distribution"].items(), key=lambda x: -x[1]):
        bar = "█" * int(pct / 2)
        print(f"    {action:20s}: {pct:5.1f}% {bar}")

    # 時間帯別の行動分布を計算（前半 vs 後半で探索→活用の変化を見る）
    half = len(state.action_log) // 2
    first_half = state.action_log[:half]
    second_half = state.action_log[half:]

    first_counts = {}
    for a in first_half:
        first_counts[a] = first_counts.get(a, 0) + 1
    second_counts = {}
    for a in second_half:
        second_counts[a] = second_counts.get(a, 0) + 1

    all_actions = sorted(set(list(first_counts.keys()) + list(second_counts.keys())))

    print(f"\n  前半 vs 後半の行動変化:")
    for a in all_actions:
        p1 = first_counts.get(a, 0) / max(1, len(first_half)) * 100
        p2 = second_counts.get(a, 0) / max(1, len(second_half)) * 100
        change = p2 - p1
        arrow = "↑" if change > 1 else ("↓" if change < -1 else "→")
        print(f"    {a:20s}: {p1:5.1f}% → {p2:5.1f}% {arrow}")

    results["first_half"] = {k: v / max(1, len(first_half)) * 100 for k, v in first_counts.items()}
    results["second_half"] = {k: v / max(1, len(second_half)) * 100 for k, v in second_counts.items()}

    # グラフ: 行動分布（棒グラフ）+ VEと疲労の時系列
    fig, axes = plt.subplots(3, 1, figsize=(14, 10))

    # 行動分布（前半vs後半）
    ax = axes[0]
    action_names = [a for a in all_actions if a not in ("blocked", "sleeping", "none")]
    x = np.arange(len(action_names))
    w = 0.35
    first_vals = [first_counts.get(a, 0) / max(1, len(first_half)) * 100 for a in action_names]
    second_vals = [second_counts.get(a, 0) / max(1, len(second_half)) * 100 for a in action_names]
    ax.bar(x - w/2, first_vals, w, label="前半（探索多め）", color="skyblue")
    ax.bar(x + w/2, second_vals, w, label="後半（活用多め）", color="steelblue")
    ax.set_xticks(x)
    ax.set_xticklabels(action_names, rotation=30, fontsize=8)
    ax.set_ylabel("選択率 (%)")
    ax.set_title("行動分布の変化（前半 vs 後半）", fontsize=10)
    ax.legend(fontsize=8)

    # VE時系列
    hours = np.arange(len(state.ve_log)) * 5 / 3600
    axes[1].plot(hours, state.ve_log, linewidth=0.5, color="steelblue")
    axes[1].set_ylabel("VE")
    axes[1].set_ylim(-5, 105)
    axes[1].set_title("仮想エネルギー推移", fontsize=10)
    for s, e in state.sleep_log:
        axes[1].axvspan(s * 5 / 3600, e * 5 / 3600, alpha=0.15, color="purple")

    # 疲労時系列
    axes[2].plot(hours, state.fatigue_log, linewidth=0.5, color="orangered")
    axes[2].set_ylabel("疲労")
    axes[2].set_ylim(-5, 105)
    axes[2].set_xlabel("時間 (h)")
    axes[2].set_title("疲労推移", fontsize=10)
    for s, e in state.sleep_log:
        axes[2].axvspan(s * 5 / 3600, e * 5 / 3600, alpha=0.15, color="purple")

    plt.tight_layout()
    plt.savefig(os.path.join(IMG_DIR, "test5_action_selection.png"), dpi=150)
    plt.close()
    print(f"\n  グラフ保存: simulation/results/test5_action_selection.png")

    return results


# =========================================
# 壊れる条件の特定
# =========================================

def find_breaking_points():
    """
    VE復帰不能、疲労回復不能、記憶全消失のパラメータ境界を特定する。
    """
    print("\n" + "=" * 60)
    print("壊れる条件の特定")
    print("=" * 60)

    # 短いデータで高速にスキャン（最初の12時間分 ≈ 8640ステップ）
    short_data = SENSOR_DATA[:8640]
    results = {}

    # --- VE復帰不能の境界 ---
    print("\n  [VE復帰不能の境界]")
    for br in [0.015, 0.02, 0.025, 0.03, 0.04, 0.05]:
        random.seed(42)
        state = SimState(base_rate=br, ve=100.0, fatigue=0.0)
        state = run_simulation(short_data, state, enable_actions=True, enable_sleep=True)
        ve_arr = np.array(state.ve_log)
        # 最後の1時間のVE平均
        last_hour = ve_arr[-720:]  # 720ステップ = 1時間
        mean_last = np.mean(last_hour) if len(last_hour) > 0 else 0
        zero_pct = np.sum(ve_arr <= 0.01) / len(ve_arr) * 100
        recoverable = mean_last > 10
        status = "OK" if recoverable else "壊れる"
        print(f"    base_rate={br}: 最終1h平均VE={mean_last:.1f}, VE=0割合={zero_pct:.1f}% → {status}")
        results[f"ve_br={br}"] = {"mean_last_hour_ve": mean_last, "zero_pct": zero_pct, "status": status}

    # --- 疲労回復不能の境界 ---
    print("\n  [疲労回復不能の境界]")
    for fr in [0.003, 0.005, 0.008, 0.01, 0.015]:
        random.seed(42)
        state = SimState(base_fatigue_rate=fr, ve=100.0, fatigue=0.0)
        state = run_simulation(short_data, state, enable_actions=True, enable_sleep=True)
        fat_arr = np.array(state.fatigue_log)
        mean_last = np.mean(fat_arr[-720:]) if len(fat_arr) > 720 else np.mean(fat_arr)
        stuck_at_max = np.sum(fat_arr >= 95) / len(fat_arr) * 100
        recoverable = stuck_at_max < 50
        status = "OK" if recoverable else "壊れる"
        print(f"    疲労率={fr}: 最終1h平均疲労={mean_last:.1f}, F≥95割合={stuck_at_max:.1f}% → {status}")
        results[f"fat_fr={fr}"] = {"mean_last_fatigue": mean_last, "stuck_pct": stuck_at_max, "status": status}

    # --- 記憶全消失の境界 ---
    print("\n  [記憶全消失の境界]")
    for mcr in [0.001, 0.003, 0.005, 0.01]:
        random.seed(42)
        state = SimState(base_rate=0.01, ve=100.0, fatigue=0.0)
        original_cost = ShortTermMemory.maintenance_cost_per_sec
        def patched_cost(self, _mcr=mcr):
            return len(self.memories) * _mcr / 60
        ShortTermMemory.maintenance_cost_per_sec = patched_cost
        state = run_simulation(short_data, state, enable_actions=True, enable_sleep=True)
        ShortTermMemory.maintenance_cost_per_sec = original_cost
        mem_arr = np.array(state.memory_count_log)
        min_mem = int(np.min(mem_arr))
        wipeouts = np.sum(mem_arr <= 20) / len(mem_arr) * 100
        status = "OK" if wipeouts < 10 else "壊れる"
        print(f"    記憶コスト率={mcr}: 最小記憶={min_mem}, ワイプアウト割合={wipeouts:.1f}% → {status}")
        results[f"mem_mcr={mcr}"] = {"min_memory": min_mem, "wipeout_pct": wipeouts, "status": status}

    return results


# =========================================
# メイン: 全テスト実行
# =========================================

def main():
    print("=" * 60)
    print("Seed0 Phase 1 シミュレーション検証")
    print("原則9: 壊れない構造を見つける")
    print("=" * 60)

    all_results = {}

    all_results["test1"] = test1_ve_depletion()
    all_results["test2"] = test2_sleep_cycle()
    all_results["test3"] = test3_comfort_zone()
    all_results["test4"] = test4_memory_cost()
    all_results["test5"] = test5_action_selection()
    all_results["breaking"] = find_breaking_points()

    # 結果をJSONで保存
    json_path = os.path.join(IMG_DIR, "results.json")
    with open(json_path, "w") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n結果JSON保存: {json_path}")

    print("\n" + "=" * 60)
    print("全テスト完了")
    print("=" * 60)

    return all_results


if __name__ == "__main__":
    main()
