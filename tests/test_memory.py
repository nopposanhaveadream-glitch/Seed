"""
memory.py の単体テスト
"""

import sys
import os
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.memory import (
    ImmediateMemory, ShortTermMemory, LongTermMemory,
    STM_MAX_SIZE, PRESSURE_TRIM_VE_LOW, PRESSURE_TRIM_VE_CRITICAL,
    PRESSURE_TRIM_MIN_KEEP, PRESSURE_TRIM_CRITICAL_KEEP
)


def test_immediate_memory():
    """即時記憶のbefore/after記録テスト。"""
    im = ImmediateMemory()
    im.record_before({"cpu": 10})
    im.record_after({"cpu": 20}, "sense_body", 0.5)
    assert im.sensors_before == {"cpu": 10}
    assert im.sensors_after == {"cpu": 20}
    assert im.last_action == "sense_body"
    assert im.last_reward == 0.5


def test_stm_store():
    """短期記憶に経験を保存できること。"""
    stm = ShortTermMemory(max_size=10)
    for i in range(5):
        stm.store({"action": f"test_{i}"}, importance=float(i))
    assert stm.count == 5


def test_stm_overflow():
    """短期記憶の容量超過時に重要度の低いものから削除されること。"""
    stm = ShortTermMemory(max_size=5)
    for i in range(10):
        stm.store({"action": f"test_{i}"}, importance=float(i))
    assert stm.count == 5
    # 残っているのは重要度の高いもの
    importances = sorted([imp for _, imp, _ in stm.memories])
    assert importances[0] >= 5.0, f"低重要度の記憶が残っている: {importances}"


def test_stm_decay():
    """記憶の重要度が減衰すること。"""
    stm = ShortTermMemory()
    stm.store({"action": "test"}, importance=1.0)
    original_imp = stm.memories[0][1]
    stm.decay()
    decayed_imp = stm.memories[0][1]
    assert decayed_imp < original_imp, f"減衰していない: {decayed_imp} >= {original_imp}"


def test_stm_maintenance_cost():
    """記憶の維持コストが件数に比例すること。"""
    stm = ShortTermMemory()
    cost_empty = stm.maintenance_cost_per_sec()
    assert cost_empty == 0.0

    for i in range(100):
        stm.store({"action": "test"}, importance=0.5)
    cost_100 = stm.maintenance_cost_per_sec()
    assert cost_100 > 0
    assert cost_100 > cost_empty


def test_stm_pressure_trim_low():
    """VE低下時に記憶が半分に圧縮されること。"""
    stm = ShortTermMemory(max_size=200)
    for i in range(100):
        stm.store({"action": f"test_{i}"}, importance=float(i) / 100)
    assert stm.count == 100

    # VE = 8 (< PRESSURE_TRIM_VE_LOW=10) で圧縮
    stm.pressure_trim(8.0)
    assert stm.count <= 50, f"圧縮されていない: {stm.count}"
    assert stm.count >= PRESSURE_TRIM_MIN_KEEP


def test_stm_pressure_trim_critical():
    """VE極低時に最小限まで圧縮されること。"""
    stm = ShortTermMemory(max_size=200)
    for i in range(100):
        stm.store({"action": f"test_{i}"}, importance=float(i) / 100)

    # VE = 2 (< PRESSURE_TRIM_VE_CRITICAL=3) で最小圧縮
    stm.pressure_trim(2.0)
    assert stm.count <= PRESSURE_TRIM_CRITICAL_KEEP, f"最小圧縮されていない: {stm.count}"


def test_stm_no_pressure_trim():
    """VEが十分なとき圧縮されないこと。"""
    stm = ShortTermMemory(max_size=200)
    for i in range(100):
        stm.store({"action": f"test_{i}"}, importance=0.5)
    stm.pressure_trim(50.0)
    assert stm.count == 100, f"VE十分なのに圧縮された: {stm.count}"


def test_stm_serialization():
    """短期記憶の永続化と復元テスト。"""
    stm = ShortTermMemory()
    stm.store({"action": "test1"}, importance=0.5)
    stm.store({"action": "test2"}, importance=0.8)

    data = stm.to_list()
    stm2 = ShortTermMemory()
    stm2.from_list(data)
    assert stm2.count == 2


def test_ltm_basic():
    """長期記憶の基本操作テスト。"""
    # テスト用の一時ファイルを使う
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmp_path = f.name

    try:
        ltm = LongTermMemory(db_path=tmp_path)

        # Q値テーブルの保存と復元
        q_table = {
            "state1": {"action1": 0.5, "action2": -0.3},
            "state2": {"action1": 0.8},
        }
        ltm.save_q_table(q_table)
        loaded = ltm.load_q_table()
        assert loaded["state1"]["action1"] == 0.5
        assert loaded["state2"]["action1"] == 0.8

        assert ltm.get_experience_count() == 0
        ltm.close()
    finally:
        os.unlink(tmp_path)


def test_ltm_consolidation():
    """長期記憶への統合テスト。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmp_path = f.name

    try:
        ltm = LongTermMemory(db_path=tmp_path)
        stm = ShortTermMemory()

        # 重要度の高い経験と低い経験を追加
        stm.store({"action": "important"}, importance=0.5)  # 統合される
        stm.store({"action": "trivial"}, importance=0.1)    # 統合されない

        consolidated = ltm.consolidate(stm)
        assert consolidated == 1, f"統合件数が不正: {consolidated}"
        assert ltm.get_experience_count() == 1

        ltm.close()
    finally:
        os.unlink(tmp_path)


def run_all():
    tests = [
        test_immediate_memory,
        test_stm_store,
        test_stm_overflow,
        test_stm_decay,
        test_stm_maintenance_cost,
        test_stm_pressure_trim_low,
        test_stm_pressure_trim_critical,
        test_stm_no_pressure_trim,
        test_stm_serialization,
        test_ltm_basic,
        test_ltm_consolidation,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ✓ {test.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ✗ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ {test.__name__}: 例外 {e}")
            failed += 1
    print(f"\n結果: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    print("=== memory.py テスト ===")
    success = run_all()
    sys.exit(0 if success else 1)
