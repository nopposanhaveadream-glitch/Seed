"""
metabolism.py の単体テスト
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.metabolism import (
    body_stress_multiplier, calculate_bmc, calculate_rest_recovery,
    calculate_sleep_recovery, clamp_ve,
    BASE_RATE, REST_VE_RECOVERY_RATE, SLEEP_VE_RECOVERY_RATE
)


def test_body_stress_multiplier_normal():
    """Phase 0の平常値ではストレス倍率が1.0であること。"""
    sensors = {
        "memory_pressure_percent": 24,
        "cpu_usage_percent": 14,
        "disk_usage_percent": 28,
    }
    bsm = body_stress_multiplier(sensors)
    assert bsm == 1.0, f"平常時のストレス倍率が1.0でない: {bsm}"


def test_body_stress_multiplier_high():
    """各指標が高いときストレスが上がること。"""
    # メモリプレッシャーだけ高い
    sensors = {"memory_pressure_percent": 40, "cpu_usage_percent": 10, "disk_usage_percent": 20}
    bsm = body_stress_multiplier(sensors)
    assert bsm > 1.0, f"メモリプレッシャー高でストレスが上がらない: {bsm}"
    assert bsm < 2.0, f"メモリプレッシャーだけで上がりすぎ: {bsm}"

    # 全部高い
    sensors = {"memory_pressure_percent": 50, "cpu_usage_percent": 70, "disk_usage_percent": 90}
    bsm = body_stress_multiplier(sensors)
    assert bsm == 4.0, f"全指標最大でストレス4.0にならない: {bsm}"


def test_body_stress_multiplier_missing_keys():
    """センサー値が欠落しても動作すること。"""
    bsm = body_stress_multiplier({})
    assert bsm == 1.0, f"空辞書でストレス1.0にならない: {bsm}"


def test_calculate_bmc_waking():
    """覚醒中のBMC計算が正しいこと。"""
    sensors = {"memory_pressure_percent": 24, "cpu_usage_percent": 14, "disk_usage_percent": 28}
    bmc = calculate_bmc(sensors, dt=5.0, is_sleeping=False)
    expected = BASE_RATE * 1.0 * 5.0  # base_rate × ストレス1.0 × 5秒
    assert abs(bmc - expected) < 0.001, f"BMC不正: {bmc} != {expected}"


def test_calculate_bmc_sleeping():
    """睡眠中のBMCが30%に低減されること。"""
    bmc_wake = calculate_bmc({"memory_pressure_percent": 24, "cpu_usage_percent": 14}, 5.0, False)
    bmc_sleep = calculate_bmc({}, 5.0, True)
    assert bmc_sleep < bmc_wake, f"睡眠中BMCが覚醒中より大きい: {bmc_sleep} >= {bmc_wake}"
    assert abs(bmc_sleep - BASE_RATE * 0.3 * 5.0) < 0.001


def test_rest_recovery():
    """rest行動のVE回復が正しいこと。"""
    recovery = calculate_rest_recovery(dt=5.0)
    expected = REST_VE_RECOVERY_RATE * 5.0
    assert abs(recovery - expected) < 0.001, f"rest回復不正: {recovery}"
    # restの回復はBMCより少ない（正味で減少）
    bmc = calculate_bmc({"memory_pressure_percent": 24, "cpu_usage_percent": 14}, 5.0, False)
    assert recovery < bmc, "rest回復がBMCを上回っている（正味で増加するのは設計違反）"


def test_sleep_recovery():
    """睡眠中のVE回復がrestより高いこと。"""
    rest = calculate_rest_recovery(5.0)
    sleep = calculate_sleep_recovery(5.0)
    assert sleep > rest, f"睡眠回復がrest以下: {sleep} <= {rest}"


def test_clamp_ve():
    """VEが有効範囲に制限されること。"""
    assert clamp_ve(-10) == 0.0
    assert clamp_ve(150) == 100.0
    assert clamp_ve(50) == 50.0


def run_all():
    """全テストを実行する。"""
    tests = [
        test_body_stress_multiplier_normal,
        test_body_stress_multiplier_high,
        test_body_stress_multiplier_missing_keys,
        test_calculate_bmc_waking,
        test_calculate_bmc_sleeping,
        test_rest_recovery,
        test_sleep_recovery,
        test_clamp_ve,
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
    print("=== metabolism.py テスト ===")
    success = run_all()
    sys.exit(0 if success else 1)
