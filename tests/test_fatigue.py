"""
fatigue.py の単体テスト
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.fatigue import (
    calculate_activity_level, calculate_fatigue_increment,
    calculate_fatigue_recovery, fatigue_cost_multiplier,
    should_force_sleep, should_wake, can_voluntary_sleep, clamp_fatigue,
    BASE_FATIGUE_RATE, ACTIVITY_FATIGUE_RATE
)


def test_activity_level_idle():
    """ベースラインど真ん中でactivity_levelが低いこと。"""
    sensors = {"cpu_usage_percent": 14, "memory_pressure_percent": 24, "load_avg_1m": 1.5}
    baseline = {"cpu_usage_percent": 14.12, "memory_pressure_percent": 24.38, "load_avg_1m": 1.5}
    level = calculate_activity_level(sensors, baseline)
    assert level < 0.05, f"アイドル時のactivity_levelが高すぎ: {level}"


def test_activity_level_high():
    """ベースラインから大きく乖離しているとactivity_levelが高いこと。"""
    sensors = {"cpu_usage_percent": 80, "memory_pressure_percent": 50, "load_avg_1m": 5.0}
    baseline = {"cpu_usage_percent": 14, "memory_pressure_percent": 24, "load_avg_1m": 1.5}
    level = calculate_activity_level(sensors, baseline)
    assert level > 0.5, f"高負荷時のactivity_levelが低すぎ: {level}"
    assert level <= 1.0, f"activity_levelが1.0を超える: {level}"


def test_fatigue_increment_basic():
    """基礎疲労が正しく蓄積すること。"""
    inc = calculate_fatigue_increment(dt=5.0, activity_level=0.0)
    expected = BASE_FATIGUE_RATE * 5.0
    assert abs(inc - expected) < 0.001, f"基礎疲労不正: {inc}"


def test_fatigue_increment_with_activity():
    """活動レベルが高いと追加疲労が発生すること。"""
    inc_idle = calculate_fatigue_increment(5.0, 0.0)
    inc_active = calculate_fatigue_increment(5.0, 1.0)
    assert inc_active > inc_idle, f"活動時の疲労がアイドル以下: {inc_active}"
    expected = (BASE_FATIGUE_RATE + ACTIVITY_FATIGUE_RATE * 1.0) * 5.0
    assert abs(inc_active - expected) < 0.001


def test_fatigue_recovery():
    """睡眠中の疲労回復が正しく動作すること。"""
    rec = calculate_fatigue_recovery(dt=5.0)
    assert rec > 0, f"疲労回復が0以下: {rec}"
    # recovery_rate=0.010で、95→0に回復するには9500秒≈2.6時間
    # 8640秒（2.4時間）では 0.010 * 8640 = 86.4 の回復
    total_recovery = calculate_fatigue_recovery(8640)
    assert total_recovery > 80, f"2.4時間の回復が少なすぎ: {total_recovery}"
    assert total_recovery < 100, f"回復量が100を超える: {total_recovery}"


def test_fatigue_cost_multiplier():
    """疲労による行動コスト倍率のテスト。"""
    assert fatigue_cost_multiplier(0) == 1.0
    assert fatigue_cost_multiplier(15) == 1.0
    assert fatigue_cost_multiplier(30) == 1.0  # ちょうど境界: (30-30)/60 = 0
    assert fatigue_cost_multiplier(31) > 1.0   # 境界を超えると上がる
    assert fatigue_cost_multiplier(60) > fatigue_cost_multiplier(31)
    assert fatigue_cost_multiplier(85) > fatigue_cost_multiplier(60)
    assert fatigue_cost_multiplier(100) > 2.0
    # 単調非減少であること
    prev = fatigue_cost_multiplier(0)
    for f in range(1, 101):
        m = fatigue_cost_multiplier(f)
        assert m >= prev - 0.001, f"疲労{f}で倍率が下がった: {m} < {prev}"
        prev = m


def test_should_force_sleep():
    """強制睡眠の条件テスト。"""
    # 疲労95以上 かつ VE5以下で強制
    assert should_force_sleep(95, 4) == True
    assert should_force_sleep(95, 10) == False  # VEが十分
    assert should_force_sleep(80, 3) == False    # 疲労が足りない
    assert should_force_sleep(90, 4) == False


def test_should_wake():
    """起床条件のテスト。"""
    assert should_wake(5, 60) == True
    assert should_wake(15, 60) == False   # 疲労が残っている
    assert should_wake(5, 40) == False    # VEが足りない


def test_can_voluntary_sleep():
    """自発的睡眠の条件テスト。"""
    assert can_voluntary_sleep(30) == True
    assert can_voluntary_sleep(29) == False


def test_clamp_fatigue():
    """疲労の範囲制限テスト。"""
    assert clamp_fatigue(-10) == 0.0
    assert clamp_fatigue(150) == 100.0
    assert clamp_fatigue(50) == 50.0


def run_all():
    tests = [
        test_activity_level_idle,
        test_activity_level_high,
        test_fatigue_increment_basic,
        test_fatigue_increment_with_activity,
        test_fatigue_recovery,
        test_fatigue_cost_multiplier,
        test_should_force_sleep,
        test_should_wake,
        test_can_voluntary_sleep,
        test_clamp_fatigue,
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
    print("=== fatigue.py テスト ===")
    success = run_all()
    sys.exit(0 if success else 1)
