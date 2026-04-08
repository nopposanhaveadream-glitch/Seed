"""
comfort_zone.py の単体テスト
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.comfort_zone import (
    RunningBaseline, evaluate_comfort_zone,
    STATUS_NORMAL, STATUS_ALERT, STATUS_EMERGENCY,
    COLD_START_BASELINE
)


def test_cold_start():
    """Cold Startで初期値が設定されること。"""
    bl = RunningBaseline()
    bl.cold_start()
    assert "cpu_usage_percent" in bl.means
    assert abs(bl.means["cpu_usage_percent"] - 14.12) < 0.01
    assert bl.variances["cpu_usage_percent"] > 0


def test_ema_update():
    """EMA更新が正しく動作すること。"""
    bl = RunningBaseline(alpha=0.1)  # テスト用に大きなalpha
    # 初回: そのまま採用
    bl.update("test", 10.0)
    assert bl.means["test"] == 10.0

    # 2回目: EMAが動く
    bl.update("test", 20.0)
    # 10 + 0.1 * (20 - 10) = 11.0
    assert abs(bl.means["test"] - 11.0) < 0.01


def test_ema_convergence():
    """多数のサンプルで平均に収束すること。"""
    bl = RunningBaseline(alpha=0.01)
    # 100を1000回入力
    for _ in range(1000):
        bl.update("test", 100.0)
    assert abs(bl.means["test"] - 100.0) < 1.0, f"収束しない: {bl.means['test']}"


def test_deviation_score_at_mean():
    """平均値での逸脱スコアが0であること。"""
    bl = RunningBaseline(alpha=0.1)
    for v in [10, 12, 14, 16, 18, 10, 12, 14, 16, 18] * 10:
        bl.update("test", v)
    score = bl.deviation_score("test", bl.means["test"])
    assert abs(score) < 0.01, f"平均値で逸脱スコアが0でない: {score}"


def test_deviation_score_increases():
    """平均から離れるほど逸脱スコアが上がること。"""
    bl = RunningBaseline(alpha=0.1)
    for v in [10, 12, 14, 16, 18] * 20:
        bl.update("test", v)
    score_near = bl.deviation_score("test", bl.means["test"] + 1)
    score_far = bl.deviation_score("test", bl.means["test"] + 10)
    assert score_far > score_near, f"遠い値のスコアが近い値以下: {score_far} <= {score_near}"


def test_comfort_zone_range():
    """comfort zoneの範囲が取得できること。"""
    bl = RunningBaseline(alpha=0.1)
    for v in [10, 12, 14, 16, 18] * 20:
        bl.update("test", v)
    lower, upper = bl.get_comfort_zone("test")
    assert lower is not None
    assert upper is not None
    assert lower < upper
    mean = bl.means["test"]
    assert lower < mean < upper


def test_evaluate_comfort_zone_normal():
    """平常値でnormalと判定されること。"""
    bl = RunningBaseline()
    bl.cold_start()
    sensors = {
        "memory_pressure_percent": 24,
        "cpu_usage_percent": 14,
        "disk_usage_percent": 28,
    }
    status = evaluate_comfort_zone(bl, sensors)
    assert status == STATUS_NORMAL, f"平常値でnormalにならない: {status}"


def test_evaluate_comfort_zone_alert():
    """逸脱値でalertまたはemergencyになること。"""
    bl = RunningBaseline()
    bl.cold_start()
    # CPU使用率を極端に高くする
    sensors = {
        "memory_pressure_percent": 24,
        "cpu_usage_percent": 80,
        "disk_usage_percent": 28,
    }
    status = evaluate_comfort_zone(bl, sensors)
    assert status in (STATUS_ALERT, STATUS_EMERGENCY), f"逸脱値でnormal: {status}"


def test_to_dict_from_dict():
    """永続化と復元が正しく動作すること。"""
    bl = RunningBaseline(alpha=0.002)
    bl.cold_start()
    for v in [20, 22, 24, 26, 28] * 10:
        bl.update("memory_pressure_percent", v)

    # 辞書に変換
    data = bl.to_dict()
    assert data["alpha"] == 0.002
    assert "memory_pressure_percent" in data["means"]

    # 復元
    bl2 = RunningBaseline()
    bl2.from_dict(data)
    assert bl2.alpha == 0.002
    assert abs(bl2.means["memory_pressure_percent"] - bl.means["memory_pressure_percent"]) < 0.001


def run_all():
    tests = [
        test_cold_start,
        test_ema_update,
        test_ema_convergence,
        test_deviation_score_at_mean,
        test_deviation_score_increases,
        test_comfort_zone_range,
        test_evaluate_comfort_zone_normal,
        test_evaluate_comfort_zone_alert,
        test_to_dict_from_dict,
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
    print("=== comfort_zone.py テスト ===")
    success = run_all()
    sys.exit(0 if success else 1)
