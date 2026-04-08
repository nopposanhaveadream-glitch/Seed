"""
v5 フルシステムシミュレーション

構造バグ3件修正 + 行動コスト再設定後のフルシステム検証。
サブシステムテストではなく、Q学習・記憶・睡眠を含む完全なエージェント動作を検証する。

検証する非破綻条件:
  C1: VE > 0 が維持される（VE=0に張り付かない）
  C2: 睡眠が発生する（疲労≥30で自発的 or 疲労≥95で強制）
  C3: 記憶が有界（500件を超えない、圧縮が動作する）

追加観察:
  - 活動比率（rest以外の行動が全体の何%か）
  - VEの傾き（3点以上で確認）
  - 睡眠サイクル
"""

import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulation.engine import load_phase0_data, run_simulation, SimState


def analyze(state: SimState, label: str):
    """シミュレーション結果を分析する。"""
    total = len(state.ve_log)
    if total == 0:
        print(f"[{label}] データなし")
        return {}

    # VE統計
    ve_min = min(state.ve_log)
    ve_max = max(state.ve_log)
    ve_avg = sum(state.ve_log) / total

    # VE=0の比率
    ve_zero_count = sum(1 for v in state.ve_log if v < 0.1)
    ve_zero_pct = ve_zero_count / total * 100

    # 覚醒中のVE統計（睡眠中を除外）
    awake_ve = [v for v, a in zip(state.ve_log, state.action_log) if a != "sleeping"]
    awake_ve_avg = sum(awake_ve) / len(awake_ve) if awake_ve else 0
    awake_ve_zero = sum(1 for v in awake_ve if v < 0.1)
    awake_ve_zero_pct = awake_ve_zero / len(awake_ve) * 100 if awake_ve else 0

    # VEの傾き（10分・20分・30分の3点で確認）
    steps_per_min = 12  # 5秒間隔で1分=12ステップ
    ve_trend = []
    for minutes in [10, 20, 30, 60, 120, 180]:
        idx = minutes * steps_per_min
        if idx < total:
            ve_trend.append((minutes, state.ve_log[idx]))

    # 行動統計
    action_counts = {}
    for a in state.action_log:
        action_counts[a] = action_counts.get(a, 0) + 1

    awake_actions = {k: v for k, v in action_counts.items() if k not in ("sleeping", "blocked", "none")}
    total_awake_actions = sum(awake_actions.values())
    rest_count = awake_actions.get("rest", 0)
    activity_count = total_awake_actions - rest_count
    activity_pct = activity_count / total_awake_actions * 100 if total_awake_actions > 0 else 0

    # 睡眠統計
    sleep_count = len(state.sleep_log)
    sleep_durations = [(end - start) * 5 / 60 for start, end in state.sleep_log]
    awake_periods = []
    prev_end = 0
    for start, end in state.sleep_log:
        if start > prev_end:
            awake_periods.append((start - prev_end) * 5 / 60)
        prev_end = end

    # 記憶統計
    mem_max = max(state.memory_count_log) if state.memory_count_log else 0
    mem_avg = sum(state.memory_count_log) / len(state.memory_count_log) if state.memory_count_log else 0
    mem_final = state.memory_count_log[-1] if state.memory_count_log else 0

    # Q学習統計
    q_states = len(state.selector.q_table)
    q_entries = sum(len(v) for v in state.selector.q_table.values())

    # 結果表示
    hours = total * 5 / 3600
    print(f"\n{'='*60}")
    print(f"  [{label}] {hours:.1f}時間シミュレーション結果")
    print(f"{'='*60}")

    print(f"\n  === C1: VE維持 ===")
    print(f"  VE平均={ve_avg:.1f}  最小={ve_min:.1f}  最大={ve_max:.1f}")
    print(f"  覚醒中VE平均={awake_ve_avg:.1f}")
    print(f"  VE=0比率: 全体{ve_zero_pct:.1f}%  覚醒中{awake_ve_zero_pct:.1f}%")
    if ve_trend:
        print(f"  VE傾き: ", end="")
        print("  →  ".join(f"{m}分={v:.1f}" for m, v in ve_trend))
    c1_pass = awake_ve_zero_pct < 5  # 覚醒中のVE=0が5%未満
    print(f"  判定: {'✓ PASS' if c1_pass else '✗ FAIL'}")

    print(f"\n  === C2: 睡眠到達 ===")
    print(f"  睡眠回数: {sleep_count}")
    if sleep_durations:
        print(f"  睡眠時間: {', '.join(f'{d:.1f}分' for d in sleep_durations[:5])}")
    if awake_periods:
        print(f"  覚醒時間: {', '.join(f'{d:.1f}分' for d in awake_periods[:5])}")
    c2_pass = sleep_count > 0 if hours >= 4 else True  # 4時間以上なら睡眠が発生すべき
    print(f"  判定: {'✓ PASS' if c2_pass else '✗ FAIL'}")

    print(f"\n  === C3: 記憶有界 ===")
    print(f"  記憶: 最大={mem_max}  平均={mem_avg:.0f}  最終={mem_final}")
    c3_pass = mem_max <= 500
    print(f"  判定: {'✓ PASS' if c3_pass else '✗ FAIL'}")

    print(f"\n  === 観察 ===")
    print(f"  活動比率: {activity_pct:.1f}% (rest以外)")
    sorted_actions = sorted(awake_actions.items(), key=lambda x: -x[1])
    print(f"  行動内訳: {', '.join(f'{a}:{c}' for a, c in sorted_actions)}")
    print(f"  Q学習: {q_states}状態 / {q_entries}エントリ / ε={state.selector.epsilon:.4f}")
    print(f"  最終疲労: {state.fatigue:.1f}")

    result = {
        "label": label,
        "hours": hours,
        "ve_avg": round(ve_avg, 2),
        "ve_min": round(ve_min, 2),
        "awake_ve_avg": round(awake_ve_avg, 2),
        "awake_ve_zero_pct": round(awake_ve_zero_pct, 2),
        "ve_trend": ve_trend,
        "activity_pct": round(activity_pct, 2),
        "sleep_count": sleep_count,
        "sleep_durations_min": [round(d, 1) for d in sleep_durations],
        "awake_periods_min": [round(d, 1) for d in awake_periods],
        "mem_max": mem_max,
        "mem_avg": round(mem_avg, 1),
        "action_counts": action_counts,
        "q_states": q_states,
        "q_entries": q_entries,
        "c1_pass": c1_pass,
        "c2_pass": c2_pass,
        "c3_pass": c3_pass,
    }
    return result


def main():
    print("Phase 0データを読み込み中...")
    data = load_phase0_data()
    print(f"  {len(data)}レコード読み込み完了")
    print(f"  シミュレーション可能時間: {len(data) * 5 / 3600:.1f}時間")

    # データを繰り返して24時間分に拡張
    target_steps = 24 * 3600 // 5  # 24時間 = 17,280ステップ
    extended_data = data * (target_steps // len(data) + 2)
    extended_data = extended_data[:target_steps + 1]

    results = []

    # === テスト1: 24時間フルシミュレーション ===
    print("\n" + "="*60)
    print("テスト1: 24時間フルシミュレーション（v5パラメータ）")
    print("="*60)
    state = SimState()
    # v4-A確定パラメータ + v5修正（行動コスト0、記憶制限、睡眠修正）
    state.rest_ve_recovery_rate = 0.012
    state.rest_bmc_fraction = 0.5

    result = run_simulation(extended_data, state, max_steps=target_steps)
    r = analyze(result, "v5-24h")
    results.append(r)

    # === テスト2: 48時間（2サイクル確認） ===
    print("\n" + "="*60)
    print("テスト2: 48時間シミュレーション（睡眠サイクル確認）")
    print("="*60)
    target_48h = 48 * 3600 // 5
    extended_48h = data * (target_48h // len(data) + 2)
    extended_48h = extended_48h[:target_48h + 1]

    state2 = SimState()
    state2.rest_ve_recovery_rate = 0.012
    state2.rest_bmc_fraction = 0.5

    result2 = run_simulation(extended_48h, state2, max_steps=target_48h)
    r2 = analyze(result2, "v5-48h")
    results.append(r2)

    # 結果を保存
    output_path = os.path.join(os.path.dirname(__file__), "results", "results_v5.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n結果を {output_path} に保存しました")

    # 全体判定
    all_pass = all(r.get("c1_pass") and r.get("c2_pass") and r.get("c3_pass") for r in results)
    print(f"\n{'='*60}")
    print(f"  総合判定: {'✓ ALL PASS' if all_pass else '✗ FAIL あり'}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
