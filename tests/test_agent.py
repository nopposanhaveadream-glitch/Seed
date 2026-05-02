"""
agent.py の単体テスト（flockベースの二重起動防止）

テスト方針:
- flock はプロセス間機構のため、競合再現には subprocess.Popen で別プロセスを
  立てる方式を使う（threading では同一プロセス内で fd を共有してしまうため
  不適切）。
- 詳細は ~/.seed0/reports/flock_failure_mode_analysis_2026-05-02.md 参照。
"""

import sys
import os
import tempfile
import subprocess
import textwrap
import time
import signal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agent import acquire_pid_lock, release_pid_lock


# ─────────────────────────────────────────────
# 子プロセス用ヘルパー: flockを取得して保持する
# ─────────────────────────────────────────────

def _make_holder_script(pid_path: str, hold_seconds: float) -> str:
    """flockを取得して指定秒数保持し続ける子プロセス用Pythonスクリプト。"""
    return textwrap.dedent(f"""
        import os, sys, fcntl, time
        fd = os.open({pid_path!r}, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            print("BLOCKED", flush=True)
            sys.exit(2)
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        print("ACQUIRED", flush=True)
        time.sleep({hold_seconds})
    """)


def _spawn_holder(pid_path: str, hold_seconds: float = 30.0):
    """flock保持の子プロセスを起動。'ACQUIRED'を読み取るまで待機して返す。"""
    proc = subprocess.Popen(
        [sys.executable, "-c", _make_holder_script(pid_path, hold_seconds)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
    )
    # 子プロセスが flock 取得（または失敗）するまで待つ（timeout 5秒）
    deadline = time.time() + 5.0
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        if line.strip() in (b"ACQUIRED", b"BLOCKED"):
            return proc, line.strip().decode()
    # タイムアウト
    proc.kill()
    proc.wait()
    raise RuntimeError("子プロセスがACQUIRED/BLOCKEDを返さなかった")


# ─────────────────────────────────────────────
# 基本的なacquire/releaseのテスト（同一プロセス内、サブプロセスなし）
# ─────────────────────────────────────────────

def test_acquire_first_returns_fd():
    """初回取得 → fd（int>=0）が返り、PIDファイルに自プロセスPIDが書き込まれる。"""
    with tempfile.NamedTemporaryFile(suffix=".pid", delete=True) as tmp:
        pid_path = tmp.name

    try:
        fd = acquire_pid_lock(pid_path)
        assert fd is not None and isinstance(fd, int) and fd >= 0, \
            f"fdが返るべき: {fd}"
        assert os.path.exists(pid_path), "PIDファイルが作成されていない"

        with open(pid_path) as f:
            written_pid = int(f.read().strip())
        assert written_pid == os.getpid(), \
            f"PIDが不正: {written_pid} != {os.getpid()}"
    finally:
        release_pid_lock(fd if 'fd' in dir() else None, pid_path)


def test_release_removes_pid_file():
    """release → PIDファイルが削除され、fdがcloseされる。"""
    with tempfile.NamedTemporaryFile(suffix=".pid", delete=True) as tmp:
        pid_path = tmp.name

    fd = acquire_pid_lock(pid_path)
    assert os.path.exists(pid_path)

    release_pid_lock(fd, pid_path)
    assert not os.path.exists(pid_path), "PIDファイルが削除されていない"


def test_release_idempotent():
    """release を二度呼んでも例外を投げない。"""
    with tempfile.NamedTemporaryFile(suffix=".pid", delete=True) as tmp:
        pid_path = tmp.name

    fd = acquire_pid_lock(pid_path)
    release_pid_lock(fd, pid_path)
    release_pid_lock(fd, pid_path)  # 2回目（fdは既にclose済み、ファイルも既に無い）
    # 例外なくここまで来ればパス


def test_release_none_fd():
    """fd=None で release を呼んでも例外を投げない（取得失敗時の安全性）。"""
    with tempfile.NamedTemporaryFile(suffix=".pid", delete=True) as tmp:
        pid_path = tmp.name

    release_pid_lock(None, pid_path)  # 何もしないで戻ること


def test_acquire_after_corrupted_pid_file():
    """PIDファイルが壊れた内容でも、誰もロックを保持していなければ取得できる。

    （旧実装はPID値をint化して os.kill で生存確認していたが、flock方式では
    PID値は情報目的のみのため、内容が壊れていても取得に影響しない。）
    """
    with tempfile.NamedTemporaryFile(suffix=".pid", delete=False) as tmp:
        pid_path = tmp.name
        tmp.write(b"not_a_number_garbage\n")

    fd = None
    try:
        fd = acquire_pid_lock(pid_path)
        assert fd is not None, "壊れた内容のPIDファイルでも取得できるべき"

        # 自プロセスPIDで上書きされている
        with open(pid_path) as f:
            written_pid = int(f.read().strip())
        assert written_pid == os.getpid()
    finally:
        release_pid_lock(fd, pid_path)


# ─────────────────────────────────────────────
# subprocess.Popen を使ったプロセス間ロックのテスト
# ─────────────────────────────────────────────

def test_flock_blocks_concurrent_process():
    """子プロセスがロック保持中 → 親がacquireすると None が返る（拒否）。"""
    with tempfile.NamedTemporaryFile(suffix=".pid", delete=True) as tmp:
        pid_path = tmp.name

    proc = None
    try:
        proc, status = _spawn_holder(pid_path, hold_seconds=10)
        assert status == "ACQUIRED", f"子プロセスが取得できなかった: {status}"

        # 親プロセスから取得を試みる → 拒否される
        fd = acquire_pid_lock(pid_path)
        assert fd is None, "子プロセスが保持中なら親のacquireはNoneを返すべき"
    finally:
        if proc is not None:
            proc.kill()
            proc.wait(timeout=5)
        release_pid_lock(None, pid_path)


def test_flock_released_on_sigkill():
    """子プロセスをSIGKILLで殺す → 親がacquireできる（kernel自動解放）。"""
    with tempfile.NamedTemporaryFile(suffix=".pid", delete=True) as tmp:
        pid_path = tmp.name

    proc = None
    fd = None
    try:
        proc, status = _spawn_holder(pid_path, hold_seconds=30)
        assert status == "ACQUIRED"

        # 親が取得を試みる → 拒否される
        fd_blocked = acquire_pid_lock(pid_path)
        assert fd_blocked is None

        # 子をSIGKILL
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=5)

        # kernel が flock を解放するまで少し待つ（macOSは即時解放だが念のため）
        deadline = time.time() + 3.0
        fd = None
        while time.time() < deadline:
            fd = acquire_pid_lock(pid_path)
            if fd is not None:
                break
            time.sleep(0.1)
        assert fd is not None, "SIGKILL後はacquireできるべき"
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        release_pid_lock(fd, pid_path)


def test_flock_released_on_normal_exit():
    """子プロセスが正常終了 → 親がacquireできる。"""
    with tempfile.NamedTemporaryFile(suffix=".pid", delete=True) as tmp:
        pid_path = tmp.name

    proc = None
    fd = None
    try:
        # hold_seconds=0.5 で短期間保持してから自然終了する子を立てる
        proc, status = _spawn_holder(pid_path, hold_seconds=0.5)
        assert status == "ACQUIRED"

        # 子が終了するまで待つ
        proc.wait(timeout=5)
        assert proc.returncode == 0, f"子プロセスは正常終了するべき: {proc.returncode}"

        # 親が取得を試みる → 成功
        deadline = time.time() + 3.0
        while time.time() < deadline:
            fd = acquire_pid_lock(pid_path)
            if fd is not None:
                break
            time.sleep(0.1)
        assert fd is not None, "子の正常終了後はacquireできるべき"
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        release_pid_lock(fd, pid_path)


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
    print("=== agent.py テスト（flockベース） ===")
    success = run_all()
    sys.exit(0 if success else 1)
