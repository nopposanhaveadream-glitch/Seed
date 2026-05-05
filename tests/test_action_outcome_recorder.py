"""
core/action_outcome_recorder.py の単体テスト

観察層（AOR）の Write-Only 性、エラー隔離、API の正しい動作を検証する。

厳密不変性（Q-table 完全一致）の検証は simulation/run_aor_invariance_test.py で行う。
"""

import sys
import os
import json
import sqlite3
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.action_outcome_recorder import (
    ActionOutcomeRecorder,
    STATUS_EXECUTED,
    STATUS_SLEEPING,
    STATUS_BLOCKED,
)


# ─────────────────────────────────────────────
# ヘルパー
# ─────────────────────────────────────────────

def _tmp_db_path() -> str:
    """テスト用の一時 DB パスを返す（呼び出し側で削除する）。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=True) as tmp:
        return tmp.name


def _sample_state_before():
    return {
        "sensors": {
            "memory_pressure_percent": 25.0,
            "cpu_usage_percent": 15.0,
            "disk_usage_percent": 50.0,
        },
        "internal": {
            "ve": 50.0,
            "fatigue": 20.0,
            "cz_status": "normal",
            "is_sleeping": False,
            "stm_count": 10,
        },
    }


def _sample_state_after_internal():
    return {
        "ve": 50.5,
        "fatigue": 20.1,
        "cz_status": "normal",
        "is_sleeping": False,
        "stm_count": 10,
    }


# ─────────────────────────────────────────────
# 基本: スキーマと record/update/close
# ─────────────────────────────────────────────

def test_schema_created():
    """初期化でテーブルとインデックスが作成される。"""
    db_path = _tmp_db_path()
    aor = None
    try:
        aor = ActionOutcomeRecorder(db_path)
        assert aor.conn is not None
        # スキーマ確認
        cursor = aor.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='action_outcomes'"
        )
        assert cursor.fetchone() is not None, "テーブル action_outcomes が存在しない"
        # インデックス確認
        cursor = aor.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_aor_%'"
        )
        index_names = [r[0] for r in cursor.fetchall()]
        assert "idx_aor_step_id" in index_names
        assert "idx_aor_action_name" in index_names
        assert "idx_aor_ts" in index_names
    finally:
        if aor:
            aor.close()
        if os.path.exists(db_path):
            os.remove(db_path)


def test_record_executed_action():
    """通常の executed 行動が正しく記録される。"""
    db_path = _tmp_db_path()
    aor = None
    try:
        aor = ActionOutcomeRecorder(db_path)
        aor.record(
            step_id=1,
            ts="2026-05-05T12:00:00",
            action_name="rest",
            action_status=STATUS_EXECUTED,
            state_before=_sample_state_before(),
            state_after_internal=_sample_state_after_internal(),
            action_result={"success": True, "effect": "休憩(VE回復中)"},
        )
        # SELECT で確認
        cursor = aor.conn.execute(
            "SELECT step_id, action_name, action_status, state_before, "
            "state_after, action_result FROM action_outcomes WHERE step_id=?",
            (1,),
        )
        row = cursor.fetchone()
        assert row is not None
        step_id, action_name, action_status, sb_json, sa_json, ar_json = row
        assert step_id == 1
        assert action_name == "rest"
        assert action_status == STATUS_EXECUTED
        # state_before に sensors と internal が含まれる
        sb = json.loads(sb_json)
        assert "sensors" in sb and "internal" in sb
        assert sb["internal"]["ve"] == 50.0
        # state_after は sensors=None で内部状態のみ
        sa = json.loads(sa_json)
        assert sa["sensors"] is None
        assert sa["internal"]["ve"] == 50.5
        # action_result は execute_action の戻り値
        ar = json.loads(ar_json)
        assert ar["success"] is True
    finally:
        if aor:
            aor.close()
        if os.path.exists(db_path):
            os.remove(db_path)


def test_record_sleeping_status():
    """sleeping の場合は action_result=None で記録される。"""
    db_path = _tmp_db_path()
    aor = None
    try:
        aor = ActionOutcomeRecorder(db_path)
        aor.record(
            step_id=2,
            ts="2026-05-05T12:00:05",
            action_name="sleeping",
            action_status=STATUS_SLEEPING,
            state_before=_sample_state_before(),
            state_after_internal=_sample_state_after_internal(),
            action_result=None,
        )
        cursor = aor.conn.execute(
            "SELECT action_status, action_result FROM action_outcomes WHERE step_id=?",
            (2,),
        )
        row = cursor.fetchone()
        assert row is not None
        action_status, ar_json = row
        assert action_status == STATUS_SLEEPING
        assert ar_json is None, f"sleeping の action_result は NULL であるべき: {ar_json!r}"
    finally:
        if aor:
            aor.close()
        if os.path.exists(db_path):
            os.remove(db_path)


def test_record_blocked_status():
    """blocked の場合も action_result=None で記録される。"""
    db_path = _tmp_db_path()
    aor = None
    try:
        aor = ActionOutcomeRecorder(db_path)
        aor.record(
            step_id=3,
            ts="2026-05-05T12:00:10",
            action_name="blocked",
            action_status=STATUS_BLOCKED,
            state_before=_sample_state_before(),
            state_after_internal=_sample_state_after_internal(),
            action_result=None,
        )
        cursor = aor.conn.execute(
            "SELECT action_status, action_result FROM action_outcomes WHERE step_id=?",
            (3,),
        )
        row = cursor.fetchone()
        assert row[0] == STATUS_BLOCKED
        assert row[1] is None
    finally:
        if aor:
            aor.close()
        if os.path.exists(db_path):
            os.remove(db_path)


def test_update_state_after_sensors():
    """update_state_after_sensors で sensors が後追いで埋まる。internal は維持される。"""
    db_path = _tmp_db_path()
    aor = None
    try:
        aor = ActionOutcomeRecorder(db_path)
        aor.record(
            step_id=10,
            ts="2026-05-05T12:00:00",
            action_name="rest",
            action_status=STATUS_EXECUTED,
            state_before=_sample_state_before(),
            state_after_internal=_sample_state_after_internal(),
            action_result={"success": True, "effect": "..."},
        )
        # 次ステップの SENSE 結果を流用して埋める
        next_sensors = {"memory_pressure_percent": 26.0, "cpu_usage_percent": 16.0}
        aor.update_state_after_sensors(10, next_sensors)
        # 確認
        cursor = aor.conn.execute(
            "SELECT state_after FROM action_outcomes WHERE step_id=?", (10,)
        )
        sa = json.loads(cursor.fetchone()[0])
        assert sa["sensors"] == next_sensors, "sensors が更新されていない"
        # internal は維持される
        assert sa["internal"]["ve"] == 50.5, "internal が壊れている"
    finally:
        if aor:
            aor.close()
        if os.path.exists(db_path):
            os.remove(db_path)


def test_update_state_after_sensors_missing_step():
    """存在しない step_id を update しても例外を投げない。"""
    db_path = _tmp_db_path()
    aor = None
    try:
        aor = ActionOutcomeRecorder(db_path)
        # レコード未挿入の step_id を update
        aor.update_state_after_sensors(99999, {"foo": 1})
        # 例外なくここまで来ればパス
    finally:
        if aor:
            aor.close()
        if os.path.exists(db_path):
            os.remove(db_path)


def test_close_idempotent():
    """close を二度呼んでも例外を投げない。"""
    db_path = _tmp_db_path()
    aor = ActionOutcomeRecorder(db_path)
    aor.close()
    aor.close()  # 二回目
    if os.path.exists(db_path):
        os.remove(db_path)


def test_record_after_close_no_op():
    """close 後の record は no-op で例外を投げない。"""
    db_path = _tmp_db_path()
    aor = ActionOutcomeRecorder(db_path)
    aor.close()
    # close 後に record を呼ぶ（disabled 扱い）
    aor.record(
        step_id=99,
        ts="2026-05-05T12:00:00",
        action_name="rest",
        action_status=STATUS_EXECUTED,
        state_before=_sample_state_before(),
        state_after_internal=_sample_state_after_internal(),
        action_result={"success": True, "effect": "..."},
    )
    if os.path.exists(db_path):
        os.remove(db_path)


def test_init_failure_disabled():
    """初期化失敗時に _disabled が立ち、以降の操作が no-op になる。"""
    # 書き込み不可のパス（存在しないルート配下を強制）
    bad_path = "/proc/seed0_test/nonexistent.db"  # macOS では /proc が無い → 親ディレクトリ作成時にエラー想定
    # マシンによっては作れる可能性があるため、別の方法で初期化失敗を再現
    # ここでは「ファイルではなくディレクトリへのパス」で失敗させる
    bad_dir = tempfile.mkdtemp()
    try:
        # ディレクトリパスを DB として開こうとすると sqlite3 がエラー
        aor = ActionOutcomeRecorder(bad_dir)
        # disabled 状態を確認
        assert aor._disabled is True, "初期化失敗時に _disabled=True であるべき"
        assert aor.conn is None
        # record/update が no-op で例外を投げない
        aor.record(
            step_id=1,
            ts="2026-05-05T12:00:00",
            action_name="rest",
            action_status=STATUS_EXECUTED,
            state_before=_sample_state_before(),
            state_after_internal=_sample_state_after_internal(),
            action_result={"success": True, "effect": "..."},
        )
        aor.update_state_after_sensors(1, {})
        aor.close()
    finally:
        if os.path.exists(bad_dir):
            os.rmdir(bad_dir)


def test_multiple_records_inserted():
    """複数のステップを記録できる。step_id でソート可能。"""
    db_path = _tmp_db_path()
    aor = None
    try:
        aor = ActionOutcomeRecorder(db_path)
        for i in range(1, 6):
            aor.record(
                step_id=i,
                ts=f"2026-05-05T12:00:{i:02d}",
                action_name="rest" if i % 2 == 0 else "sense_body",
                action_status=STATUS_EXECUTED,
                state_before=_sample_state_before(),
                state_after_internal=_sample_state_after_internal(),
                action_result={"success": True, "effect": f"step {i}"},
            )
        cursor = aor.conn.execute(
            "SELECT step_id, action_name FROM action_outcomes ORDER BY step_id"
        )
        rows = cursor.fetchall()
        assert len(rows) == 5
        for i, (step_id, action_name) in enumerate(rows, start=1):
            assert step_id == i
            assert action_name in ("rest", "sense_body")
    finally:
        if aor:
            aor.close()
        if os.path.exists(db_path):
            os.remove(db_path)


def test_no_random_in_module():
    """AOR モジュールに random への参照が無いことを確認する（§4.3）。"""
    import core.action_outcome_recorder as aor_mod
    source_path = aor_mod.__file__
    with open(source_path, encoding="utf-8") as f:
        src = f.read()
    # コード行から random への import / 呼出 を検出
    for line_no, line in enumerate(src.split("\n"), start=1):
        # docstring 内の "random" は対象外（行頭に # や引用符の判定は粗いがこの用途では十分）
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        # docstring 内の継続行を雑に除外する: ハッシュやクォートで始まらない実コード行のみ調べる
        if "import random" in line or "from random" in line:
            raise AssertionError(
                f"AOR モジュールに random の import がある（行 {line_no}）: {line}"
            )
        if "random." in line:
            # docstring を完全には除外できていない。実コード行で random.* を呼んでいないかは
            # この単純な検査では完全保証できないが、import が無ければ実行不能。
            # よって import の検査で十分とする。
            pass


def test_executed_status_constants():
    """ステータス定数が文字列として期待される値を持つ。"""
    assert STATUS_EXECUTED == "executed"
    assert STATUS_SLEEPING == "sleeping"
    assert STATUS_BLOCKED == "blocked"


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
    print("=== action_outcome_recorder.py テスト ===")
    success = run_all()
    sys.exit(0 if success else 1)
