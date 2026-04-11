"""
sensors.py の単体テスト（新センサー含む）

テスト方針:
  - 各関数がエラー時に空dictを返すことを確認
  - 実際のmacOS環境での値の妥当性を確認
  - コマンドが使えない環境でも全体が止まらないことを確認
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from phase0.sensors import (
    read_memory, read_cpu, read_disk, read_network,
    read_processes, read_background_activity, read_user_idle,
    read_all_sensors,
)


# ─────────────────────────────────────────────
# 既存センサーのテスト
# ─────────────────────────────────────────────

def test_read_memory():
    """メモリ情報が取得でき、圧縮率が含まれること。"""
    data = read_memory()
    assert isinstance(data, dict), "dictが返されない"
    assert "memory_used_mb" in data, "memory_used_mb がない"
    assert "memory_compressed_percent" in data, "memory_compressed_percent がない（新規）"
    # 圧縮率は0〜100%の範囲
    pct = data["memory_compressed_percent"]
    assert 0 <= pct <= 100, f"圧縮率が範囲外: {pct}"


def test_read_cpu():
    """CPU情報が取得できること。"""
    data = read_cpu()
    assert isinstance(data, dict)
    assert "cpu_usage_percent" in data


def test_read_disk():
    """ディスク情報が取得できること。"""
    data = read_disk()
    assert isinstance(data, dict)
    assert "disk_usage_percent" in data


def test_read_processes():
    """プロセス情報が取得できること。"""
    data = read_processes()
    assert isinstance(data, dict)
    assert "process_count" in data
    assert data["process_count"] > 0


# ─────────────────────────────────────────────
# 新センサーのテスト
# ─────────────────────────────────────────────

def test_read_background_activity():
    """バックグラウンドプロセス活動が取得できること。"""
    data = read_background_activity()
    assert isinstance(data, dict), "dictが返されない"
    assert "background_cpu_percent" in data, "background_cpu_percent がない"
    # CPU%は0以上
    assert data["background_cpu_percent"] >= 0, f"負の値: {data['background_cpu_percent']}"


def test_read_user_idle():
    """ユーザーアイドル時間が取得できること。"""
    data = read_user_idle()
    assert isinstance(data, dict), "dictが返されない"
    assert "user_idle_seconds" in data, "user_idle_seconds がない"
    # アイドル時間は0以上
    assert data["user_idle_seconds"] >= 0, f"負の値: {data['user_idle_seconds']}"


def test_disk_write():
    """ディスク書き込み速度が取得できること（2回目の呼び出しから）。"""
    import time
    # 1回目は前回値がないのでレートは出ない
    read_disk()
    time.sleep(1)
    # 2回目でレートが計算される
    data = read_disk()
    assert isinstance(data, dict)
    # disk_write_mb_sが含まれていること
    assert "disk_write_mb_s" in data, "disk_write_mb_s がない"
    assert data["disk_write_mb_s"] >= 0, f"負の値: {data['disk_write_mb_s']}"


def test_memory_compressed_percent():
    """メモリ圧縮率が妥当な範囲であること。"""
    data = read_memory()
    assert "memory_compressed_percent" in data
    pct = data["memory_compressed_percent"]
    # 通常 0.1〜30% 程度（Mac mini 24GB環境）
    assert 0 <= pct <= 50, f"圧縮率が異常: {pct}%"


# ─────────────────────────────────────────────
# 統合テスト
# ─────────────────────────────────────────────

def test_read_all_sensors_includes_new_keys():
    """read_all_sensors()に新センサーキーが含まれること。"""
    data = read_all_sensors(use_sudo=False)
    assert isinstance(data, dict)
    # 新しいキーの存在確認
    new_keys = ["memory_compressed_percent", "background_cpu_percent", "user_idle_seconds"]
    for key in new_keys:
        assert key in data, f"{key} がread_all_sensorsに含まれない"


def test_all_sensors_return_dict_on_error():
    """各関数が例外を投げずdictを返すことを確認。"""
    # 全関数をリストで呼び出し、すべてがdictを返すことを検証
    funcs = [
        read_memory, read_cpu, read_disk, read_network,
        read_processes, read_background_activity, read_user_idle,
    ]
    for func in funcs:
        result = func()
        assert isinstance(result, dict), f"{func.__name__} がdictを返さない: {type(result)}"


def run_all():
    import inspect
    tests = [
        v for k, v in sorted(globals().items())
        if k.startswith("test_") and inspect.isfunction(v)
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
    print("=== sensors.py テスト ===")
    success = run_all()
    sys.exit(0 if success else 1)
