"""
agent.py の単体テスト（PIDファイルによる二重起動防止）
"""

import sys
import os
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agent import ensure_single_instance, remove_pid_file


def test_pid_file_created_on_first_start():
    """PIDファイルが存在しない状態で起動 → PIDファイルが作成される。"""
    with tempfile.NamedTemporaryFile(suffix=".pid", delete=True) as tmp:
        pid_path = tmp.name  # 一時ファイルは自動削除済み

    try:
        result = ensure_single_instance(pid_path)
        assert result is True, "起動が許可されるべき"
        assert os.path.exists(pid_path), "PIDファイルが作成されていない"

        with open(pid_path) as f:
            written_pid = int(f.read().strip())
        assert written_pid == os.getpid(), f"PIDが不正: {written_pid} != {os.getpid()}"
    finally:
        remove_pid_file(pid_path)


def test_pid_file_blocks_duplicate():
    """有効なPIDのPIDファイルが存在 → 起動拒否される。"""
    with tempfile.NamedTemporaryFile(suffix=".pid", delete=True) as tmp:
        pid_path = tmp.name

    try:
        # 自プロセスのPIDを書き込む（確実に生存しているPID）
        os.makedirs(os.path.dirname(pid_path), exist_ok=True)
        with open(pid_path, "w") as f:
            f.write(str(os.getpid()))

        # 同じPIDファイルで再度起動を試みる → 拒否
        result = ensure_single_instance(pid_path)
        assert result is False, "二重起動が拒否されるべき"
    finally:
        remove_pid_file(pid_path)


def test_stale_pid_file_cleaned():
    """古いPID（存在しないプロセス）のPIDファイル → 警告を出して起動続行。"""
    with tempfile.NamedTemporaryFile(suffix=".pid", delete=True) as tmp:
        pid_path = tmp.name

    try:
        # 存在しないPIDを書き込む（99999999は通常存在しない）
        stale_pid = 99999999
        os.makedirs(os.path.dirname(pid_path), exist_ok=True)
        with open(pid_path, "w") as f:
            f.write(str(stale_pid))

        # 古いPIDなので起動が許可される
        result = ensure_single_instance(pid_path)
        assert result is True, "古いPIDファイルがある場合は起動を許可すべき"

        # PIDファイルが自プロセスのPIDに更新される
        with open(pid_path) as f:
            new_pid = int(f.read().strip())
        assert new_pid == os.getpid(), f"PIDが更新されていない: {new_pid}"
    finally:
        remove_pid_file(pid_path)


def test_pid_file_removed_on_cleanup():
    """remove_pid_file()でPIDファイルが削除される。"""
    with tempfile.NamedTemporaryFile(suffix=".pid", delete=True) as tmp:
        pid_path = tmp.name

    # PIDファイルを作成
    ensure_single_instance(pid_path)
    assert os.path.exists(pid_path), "PIDファイルが作成されていない"

    # 削除
    remove_pid_file(pid_path)
    assert not os.path.exists(pid_path), "PIDファイルが削除されていない"


def test_remove_nonexistent_pid_file():
    """存在しないPIDファイルの削除は例外を投げない。"""
    remove_pid_file("/tmp/nonexistent_seed0_test.pid")
    # 例外が出なければパス


def test_corrupted_pid_file():
    """PIDファイルが壊れている場合 → 削除して起動続行。"""
    with tempfile.NamedTemporaryFile(suffix=".pid", delete=True) as tmp:
        pid_path = tmp.name

    try:
        os.makedirs(os.path.dirname(pid_path), exist_ok=True)
        with open(pid_path, "w") as f:
            f.write("not_a_number")

        result = ensure_single_instance(pid_path)
        assert result is True, "壊れたPIDファイルは無視して起動すべき"
    finally:
        remove_pid_file(pid_path)


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
    print("=== agent.py テスト ===")
    success = run_all()
    sys.exit(0 if success else 1)
