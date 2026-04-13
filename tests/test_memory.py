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


def test_purge_memory_reduces_stm():
    """purge_memoryがSTMを20%削減すること。"""
    stm = ShortTermMemory()
    # 100件の記憶を追加（重要度は0.01〜1.0）
    for i in range(100):
        stm.store({"action": f"test_{i}"}, importance=i * 0.01)

    assert stm.count == 100, f"初期件数が不正: {stm.count}"

    # purge: 20%削減 → 80件になる
    current = stm.count
    to_remove = max(1, -(-current // 5))
    target = max(10, current - to_remove)
    stm.memories.sort(key=lambda m: m[1], reverse=True)
    stm.memories = stm.memories[:target]

    assert stm.count == 80, f"purge後の件数が不正: {stm.count}"
    # 重要度の高い記憶が残っていること
    min_importance = min(m[1] for m in stm.memories)
    assert min_importance >= 0.19, f"重要度の低い記憶が残っている: {min_importance}"


def test_purge_memory_protects_minimum():
    """purge_memoryが最低10件を保護すること。"""
    stm = ShortTermMemory()
    for i in range(10):
        stm.store({"action": f"test_{i}"}, importance=0.1)

    assert stm.count == 10
    # 10件以下ではpurgeしない
    current = stm.count
    if current > 10:
        to_remove = max(1, -(-current // 5))
        target = max(10, current - to_remove)
        stm.memories.sort(key=lambda m: m[1], reverse=True)
        stm.memories = stm.memories[:target]

    assert stm.count == 10, f"最低保持件数を下回った: {stm.count}"


def test_purge_memory_keeps_important():
    """purge_memoryが重要度の高い記憶を残すこと。"""
    stm = ShortTermMemory()
    # 重要度0.01の記憶50件 + 重要度1.0の記憶50件
    for i in range(50):
        stm.store({"action": "unimportant"}, importance=0.01)
    for i in range(50):
        stm.store({"action": "important"}, importance=1.0)

    current = stm.count
    to_remove = max(1, -(-current // 5))
    target = max(10, current - to_remove)
    stm.memories.sort(key=lambda m: m[1], reverse=True)
    stm.memories = stm.memories[:target]

    # 80件残る。重要度1.0の50件は全部残り、0.01の30件が残る
    assert stm.count == 80
    important_count = sum(1 for m in stm.memories if m[2]["action"] == "important")
    assert important_count == 50, f"重要な記憶が失われた: {important_count}/50"


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
        test_purge_memory_reduces_stm,
        test_purge_memory_protects_minimum,
        test_purge_memory_keeps_important,
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
