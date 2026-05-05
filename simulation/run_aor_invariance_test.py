"""
AOR 厳密不変性テスト(simulation 統合テスト)

観察層(AOR)の有無で Q-table が **完全一致** することを検証する。

判定基準(依頼書 v3 §4.3):
  - 同じ random seed と同じ canned sensor data で N ステップ実行したとき、
    観察層あり/なしの両ケースで Q-table のキーも値も小数点表現まで完全一致
  - 観察層モジュール内に random 呼出が無いことを grep で確認

設計上、core/* の本番コードパスを使う(simulation/engine.py の平行実装ではない)。

決定論性の確保:
  - random.seed(SEED) を各 run の冒頭で設定
  - sensors は Phase 0 DB から読み込んだ canned data(両 run で同一)
  - time.time() は simulation 形式でモック(base + step * dt)
    → 行動 cooldown が決定論的に決まる
  - AgentState は cold_start_from_db=False で初期化
    (live long_term.db からの Q-table 読み込みは両 run で同じため、無くても可だが
     テスト isolation のため空 Q-table から始めない場合もある)

Phase 0 データが取得できない場合はテストをスキップする。
"""

import sys
import os
import random
import sqlite3
import json
import tempfile
from copy import deepcopy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# core/* の本番コードを直接駆動
from core.state import AgentState
from core.unconscious import UnconsciousProcess
from core.conscious import ConsciousProcess
from core.comfort_zone import evaluate_comfort_zone
from core.action_outcome_recorder import (
    ActionOutcomeRecorder,
    STATUS_EXECUTED,
    STATUS_SLEEPING,
    STATUS_BLOCKED,
)
import core.conscious  # time.time モック用


# ─────────────────────────────────────────────
# Canned sensor data ロード
# ─────────────────────────────────────────────

def load_canned_sensors(n_steps: int) -> list:
    """Phase 0 DB から N+1 件のセンサーレコードを取得。

    無ければ None を返す(その場合、不変性テストはスキップされる)。
    """
    db_path = os.path.expanduser("~/.seed0/phase0/body_data.db")
    if not os.path.exists(db_path):
        return None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM body_sensor_readings ORDER BY id LIMIT ?",
            (n_steps + 2,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows if len(rows) >= n_steps + 1 else None
    except Exception:
        return None


# ─────────────────────────────────────────────
# 1 run 分の実行
# ─────────────────────────────────────────────

def run_agent_loop(
    canned_sensors: list,
    n_steps: int,
    seed: int,
    with_aor: bool,
    aor_db_path: str = None,
) -> dict:
    """指定設定で N ステップ走らせ、最終 Q-table の deepcopy を返す。"""
    # 決定論性の確保
    random.seed(seed)

    # state を fresh に作る(initialize は呼ばない: long_term.db への依存を避ける)
    # AgentState.__init__ で long_term_memory が live DB を開くので、
    # ここでは live DB の状態を使う(両 run で同じ初期 Q-table)。
    state = AgentState()

    unconscious = UnconsciousProcess()
    conscious = ConsciousProcess()
    # Q-table を共有(本番の Seed0Agent.__init__ と同じ)
    conscious.selector = state.action_selector

    aor = None
    if with_aor:
        aor = ActionOutcomeRecorder(aor_db_path)

    aor_prev_step_id = None
    dt = 5.0
    base_time = 1_000_000.0  # 任意の固定値

    # time.time() をモック(両 run で同じ進行)
    original_time = core.conscious.time.time

    try:
        for i in range(min(n_steps, len(canned_sensors) - 1)):
            sensors = canned_sensors[i]
            state.step()

            # AOR: 前ステップ sensors_after を埋める
            if aor is not None and aor_prev_step_id is not None:
                aor.update_state_after_sensors(aor_prev_step_id, sensors)

            state.immediate_memory.record_before(sensors)
            state.prev_sensors = state.latest_sensors
            state.latest_sensors = sensors

            # time.time() を simulation 形式で固定
            current_time = base_time + i * dt
            core.conscious.time.time = lambda t=current_time: t

            # METABOLIZE
            unconscious.tick(state, sensors, dt)

            # CZ status update
            state.comfort_zone_status = evaluate_comfort_zone(
                state.baseline, sensors
            )

            # AOR: state_before 内部状態スナップショット
            aor_state_before_internal = None
            if aor is not None:
                aor_state_before_internal = {
                    "ve": state.ve,
                    "fatigue": state.fatigue,
                    "cz_status": state.comfort_zone_status,
                    "is_sleeping": state.is_sleeping,
                    "stm_count": state.short_term_memory.count,
                }

            # think_and_act(本番と同じ)
            chosen = conscious.think_and_act(
                state, sensors, state.prev_sensors, dt
            )

            # AOR: state_after 内部状態 + record
            if aor is not None and aor_state_before_internal is not None:
                aor_state_after_internal = {
                    "ve": state.ve,
                    "fatigue": state.fatigue,
                    "cz_status": state.comfort_zone_status,
                    "is_sleeping": state.is_sleeping,
                    "stm_count": state.short_term_memory.count,
                }
                if chosen == "sleeping":
                    status, result = STATUS_SLEEPING, None
                elif chosen == "blocked":
                    status, result = STATUS_BLOCKED, None
                else:
                    status = STATUS_EXECUTED
                    result = getattr(conscious, "last_action_result", None)
                aor.record(
                    step_id=state.total_steps,
                    ts=f"step{state.total_steps:08d}",
                    action_name=chosen,
                    action_status=status,
                    state_before={
                        "sensors": sensors,
                        "internal": aor_state_before_internal,
                    },
                    state_after_internal=aor_state_after_internal,
                    action_result=result,
                )
                aor_prev_step_id = state.total_steps
    finally:
        # time.time() のモック解除
        core.conscious.time.time = original_time
        if aor is not None:
            aor.close()
        # state の long_term.db / agent_state.db は閉じる(save はしない)
        try:
            state.long_term_memory.close()
        except Exception:
            pass

    # 最終 Q-table を deepcopy で返す(以降の変更から保護)
    return deepcopy(state.action_selector.q_table)


# ─────────────────────────────────────────────
# Q-table 比較
# ─────────────────────────────────────────────

def compare_q_tables(qt1: dict, qt2: dict) -> tuple:
    """完全一致を確認。一致していれば (True, msg)、不一致なら (False, msg)。"""
    if set(qt1.keys()) != set(qt2.keys()):
        diff = set(qt1.keys()) ^ set(qt2.keys())
        return False, f"states 集合の差分: {sorted(diff)}"
    for state_key, actions1 in sorted(qt1.items()):
        actions2 = qt2.get(state_key, {})
        if set(actions1.keys()) != set(actions2.keys()):
            diff = set(actions1.keys()) ^ set(actions2.keys())
            return False, f"state {state_key} の action 差分: {sorted(diff)}"
        for a, q1 in sorted(actions1.items()):
            q2 = actions2.get(a)
            # 浮動小数点の bit レベル比較
            if q1 != q2:
                return (
                    False,
                    f"({state_key}, {a}) の Q値不一致: {q1!r} vs {q2!r}",
                )
    return True, "完全一致"


# ─────────────────────────────────────────────
# テスト
# ─────────────────────────────────────────────

def test_strict_invariance():
    """AOR の有無で Q-table が完全一致(byte-identical)であることを確認。"""
    SEED = 42
    N_STEPS = 500

    canned = load_canned_sensors(N_STEPS)
    if canned is None or len(canned) < N_STEPS + 1:
        print("  ⚠ Phase 0 DB が未準備のためスキップ")
        return

    # Run 1: AOR 無し
    qt_without = run_agent_loop(canned, N_STEPS, SEED, with_aor=False)

    # Run 2: AOR 有り
    aor_path = tempfile.mktemp(suffix=".db")
    try:
        qt_with = run_agent_loop(
            canned, N_STEPS, SEED, with_aor=True, aor_db_path=aor_path
        )
    finally:
        if os.path.exists(aor_path):
            os.remove(aor_path)
        # WAL/journal ファイルも削除
        for ext in ("-wal", "-shm", "-journal"):
            p = aor_path + ext
            if os.path.exists(p):
                os.remove(p)

    # 完全一致を確認
    ok, msg = compare_q_tables(qt_without, qt_with)
    n_states_without = len(qt_without)
    n_entries_without = sum(len(v) for v in qt_without.values())
    n_states_with = len(qt_with)
    n_entries_with = sum(len(v) for v in qt_with.values())
    print(f"  AOR 無し: {n_states_without} 状態 / {n_entries_without} エントリ")
    print(f"  AOR 有り: {n_states_with} 状態 / {n_entries_with} エントリ")
    print(f"  → {msg}")
    assert ok, f"Q-table が完全一致しない: {msg}"


def test_no_random_in_aor_module():
    """AOR モジュールのコード行に random 参照が無いことを確認(§4.3)。"""
    aor_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "core",
        "action_outcome_recorder.py",
    )
    with open(aor_path, encoding="utf-8") as f:
        src = f.read()

    # docstring を粗く除外しつつ、コード行を抽出
    code_lines = []
    in_module_docstring = False
    triple_quote_count = 0
    for line in src.split("\n"):
        stripped = line.strip()
        # 三重引用符の出現で docstring 状態を切り替え
        if '"""' in stripped or "'''" in stripped:
            triple_quote_count += stripped.count('"""') + stripped.count("'''")
            # 同一行で開閉する場合(""" docstring """)もカウント
            in_module_docstring = (triple_quote_count % 2) == 1
            continue
        if in_module_docstring:
            continue
        if stripped.startswith("#"):
            continue
        code_lines.append(line)

    code = "\n".join(code_lines)
    assert "import random" not in code, (
        "AOR コード行に import random がある"
    )
    assert "from random" not in code, "AOR コード行に from random がある"
    # random.* の呼び出しもチェック(import が無ければ実行不能だが念のため)
    assert "random." not in code, "AOR コード行に random.* の呼び出しがある"
    print("  → AOR コード行に random への参照なし(import/呼出いずれも)")


# ─────────────────────────────────────────────
# 実行
# ─────────────────────────────────────────────

def run_all():
    import inspect
    tests = [
        v for k, v in sorted(globals().items())
        if k.startswith("test_") and inspect.isfunction(v)
    ]
    passed = 0
    failed = 0
    for test in tests:
        print(f"--- {test.__name__} ---")
        try:
            test()
            print(f"  ✓ PASS")
            passed += 1
        except AssertionError as e:
            print(f"  ✗ FAIL: {e}")
            failed += 1
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  ✗ EXCEPTION: {e}")
            failed += 1
    print(f"\n結果: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    print("=== AOR 厳密不変性テスト(simulation/run_aor_invariance_test.py)===")
    success = run_all()
    sys.exit(0 if success else 1)
