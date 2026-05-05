"""
Seed0 Phase 1 — Action Outcome Recorder（AOR、観察層）

行動の前後の状態スナップショットを SQLite に記録する純粋な観察層。
Q学習・行動選択・代謝・記憶には影響しない（Write-Only）。

設計判断の根拠:
  - prompts/action_outcome_recorder_implementation_request_v3.md（再構築 v3）
  - ~/.seed0/reports/action_interface_survey_2026-05-05.md（Code ステップ1 レポート）
  - ~/.seed0/reports/aor_storage_analysis_2026-05-05.md（Code ステップ2 レポート）
  - 設計議論側からの判断確定（2026-05-05）:
    - ストレージ案: 案A（並走）、`~/.seed0/memory/action_outcomes.db` を新規
    - 行動の出力結果: 案2（state diff で間接推定、actions.py は触らない）
    - state_after の sensors: オプション B（次ステップの SENSE 結果を流用）
    - VE コスト消費の記録対象化: しない（rest の ve_cost=0、他は state diff で分解可能）
    - 早期 return 経路（sleeping/blocked）: 記録する（step_trace と 1:1 対応）

構造的な制約（依頼書 v3 §4 を反映）:
  - §4.1 Write-Only 性: state を read-only でアクセス、変更しない
  - §4.2 エラー隔離: 全体を try/except で囲み、例外は主処理に伝播させない
  - §4.3 厳密不変性: random モジュールを一切使わない（grep で確認可能）

注意:
  - state_after の sensors は record() 時点では None で記録され、
    次ステップで update_state_after_sensors() により埋められる。
  - 各ステップの最後のレコードは sensors_after が埋まらない状態で残る
    （構造的な制約、shutdown 時に最後のステップ分は不完全になる）。
"""

import os
import json
import logging
import sqlite3
from typing import Optional

logger = logging.getLogger("seed0")

# 既定のデータベースパス
DB_PATH = os.path.expanduser("~/.seed0/memory/action_outcomes.db")

# action_status の定数
STATUS_EXECUTED = "executed"
STATUS_SLEEPING = "sleeping"
STATUS_BLOCKED = "blocked"


class ActionOutcomeRecorder:
    """行動前後の状態スナップショットを SQLite に記録する観察層。

    使い方:
        aor = ActionOutcomeRecorder()

        # 各ステップで:
        aor.record(
            step_id=N,
            ts="2026-05-05T12:34:56",
            action_name="rest",
            action_status="executed",
            state_before={"sensors": {...全25キー}, "internal": {...}},
            state_after_internal={...},  # この時点では sensors は埋まらない
            action_result={"success": True, "effect": "..."},
        )

        # 次ステップ冒頭で前ステップの sensors_after を埋める:
        aor.update_state_after_sensors(step_id=N, sensors={...})

        # シャットダウン時:
        aor.close()
    """

    def __init__(self, db_path: str = DB_PATH):
        """初期化。DB 接続失敗時はフラグを立てて以降の操作を no-op にする。"""
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self._disabled = False
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            # isolation_level=None で autocommit にせず、明示的に commit する
            self.conn = sqlite3.connect(self.db_path)
            # WAL モードで読み書きの並行性を確保
            self.conn.execute("PRAGMA journal_mode=WAL")
            self._create_schema()
        except Exception as e:
            logger.warning(f"AOR 初期化失敗（記録は無効化、主処理は継続）: {e}")
            self._disabled = True
            if self.conn is not None:
                try:
                    self.conn.close()
                except Exception:
                    pass
                self.conn = None

    def _create_schema(self):
        """テーブルとインデックスを作成する（冪等）。"""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS action_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                step_id INTEGER NOT NULL,
                ts TEXT NOT NULL,
                action_name TEXT NOT NULL,
                action_status TEXT NOT NULL,
                state_before TEXT NOT NULL,
                state_after TEXT,
                action_result TEXT
            )
        """)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_aor_step_id "
            "ON action_outcomes(step_id)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_aor_action_name "
            "ON action_outcomes(action_name)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_aor_ts ON action_outcomes(ts)"
        )
        self.conn.commit()

    def record(
        self,
        step_id: int,
        ts: str,
        action_name: str,
        action_status: str,
        state_before: dict,
        state_after_internal: dict,
        action_result: Optional[dict],
    ) -> None:
        """1ステップ分のレコードを INSERT する。

        引数:
            step_id: state.total_steps の値
            ts: ISO 8601 タイムスタンプ文字列
            action_name: 選択された行動名（"sleeping"/"blocked" を含む）
            action_status: STATUS_EXECUTED / STATUS_SLEEPING / STATUS_BLOCKED
            state_before: {"sensors": {...全25キー}, "internal": {ve, fatigue, ...}}
            state_after_internal: {ve, fatigue, cz_status, is_sleeping, stm_count}
                ※ sensors はこの時点で未確定のため後追いで update する
            action_result: execute_action の戻り値、または None（早期 return 時）

        例外は内部で隔離する（§4.2）。記録漏れの事実は logger.warning に残す。
        """
        if self._disabled or self.conn is None:
            return
        try:
            # state_after は sensors=None で初期化、内部状態のみ含める
            state_after_record = {
                "sensors": None,
                "internal": state_after_internal,
            }
            self.conn.execute(
                """
                INSERT INTO action_outcomes
                  (step_id, ts, action_name, action_status,
                   state_before, state_after, action_result)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    step_id,
                    ts,
                    action_name,
                    action_status,
                    json.dumps(state_before, ensure_ascii=False, sort_keys=True),
                    json.dumps(
                        state_after_record, ensure_ascii=False, sort_keys=True
                    ),
                    (
                        json.dumps(
                            action_result, ensure_ascii=False, sort_keys=True
                        )
                        if action_result is not None
                        else None
                    ),
                ),
            )
            self.conn.commit()
        except Exception as e:
            # §4.2: 記録漏れの事実をログに残す（無音で失敗しない）
            logger.warning(
                f"AOR record 失敗（step={step_id}, action={action_name}）: {e}"
            )

    def update_state_after_sensors(self, step_id: int, sensors: dict) -> None:
        """指定 step_id のレコードの state_after.sensors を後追いで埋める。

        次ステップの SENSE 結果（オプション B）を state_after として流用する。
        record() 時点では state_after.sensors=None だったものを上書きする。
        既存の state_after.internal は保持する。

        例外は内部で隔離する。
        """
        if self._disabled or self.conn is None:
            return
        try:
            cursor = self.conn.execute(
                "SELECT state_after FROM action_outcomes WHERE step_id = ?",
                (step_id,),
            )
            row = cursor.fetchone()
            if row is None or row[0] is None:
                # 該当レコードが見つからない場合は何もしない
                logger.warning(
                    f"AOR update_state_after_sensors: step_id={step_id} の"
                    f"レコードが見つからない"
                )
                return
            existing = json.loads(row[0])
            existing["sensors"] = sensors
            self.conn.execute(
                "UPDATE action_outcomes SET state_after = ? WHERE step_id = ?",
                (
                    json.dumps(existing, ensure_ascii=False, sort_keys=True),
                    step_id,
                ),
            )
            self.conn.commit()
        except Exception as e:
            logger.warning(
                f"AOR state_after sensors 更新失敗（step={step_id}）: {e}"
            )

    def close(self) -> None:
        """接続を閉じる（冪等）。"""
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception as e:
                logger.warning(f"AOR close 失敗: {e}")
            self.conn = None
        self._disabled = True
