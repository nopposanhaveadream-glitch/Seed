"""
Seed0 Phase 1 — 記憶（Memory）モジュール

3層の記憶システム:
  即時記憶: 直近1ステップ分（変数）
  短期記憶: 最大500件（インメモリ、VEコストあり）
  長期記憶: 最大10,000件（SQLite永続）

記憶にはVEコストがかかる。無限に覚え続けることはできない。
VE不足時に記憶が圧縮される = 何を覚え何を忘れるかが構造的に決まる。

確定パラメータ:
  - 短期記憶コスト: 0.001 VE/件/分
  - pressure_trim閾値: VE < 10 で半減、VE < 3 で最小限
"""

import sqlite3
import os
import json
import time
from typing import Optional


# ─────────────────────────────────────────────
# 確定パラメータ
# ─────────────────────────────────────────────

# 短期記憶の最大件数
STM_MAX_SIZE = 500

# 短期記憶の維持コスト（VE/件/分）
STM_COST_PER_ITEM_PER_MIN = 0.001

# 短期記憶の減衰率（毎分適用）
STM_DECAY_RATE = 0.999

# 記憶圧縮の閾値
PRESSURE_TRIM_VE_LOW = 10.0    # VEがこの値未満で記憶を半分に
PRESSURE_TRIM_VE_CRITICAL = 3.0  # VEがこの値未満で最小限に
PRESSURE_TRIM_MIN_KEEP = 50     # 最低限保持する件数
PRESSURE_TRIM_CRITICAL_KEEP = 20  # 危機的状況で保持する件数

# 長期記憶の最大件数
LTM_MAX_SIZE = 10000

# 長期記憶への統合閾値（重要度がこの値以上で統合対象）
CONSOLIDATION_THRESHOLD = 0.3

# 長期記憶のデータベースパス
LTM_DB_PATH = os.path.expanduser("~/.seed0/memory/long_term.db")


# ─────────────────────────────────────────────
# 即時記憶（Immediate Memory）
# ─────────────────────────────────────────────

class ImmediateMemory:
    """
    直近1ステップ分のセンサー値と行動結果。
    常に上書きされる。行動のbefore/after比較に使う。
    コストなし。
    """

    def __init__(self):
        self.sensors_before = {}
        self.sensors_after = {}
        self.last_action = None
        self.last_reward = 0.0

    def record_before(self, sensors: dict):
        """行動前のセンサー値を記録する。"""
        self.sensors_before = dict(sensors)

    def record_after(self, sensors: dict, action: str, reward: float):
        """行動後のセンサー値と結果を記録する。"""
        self.sensors_after = dict(sensors)
        self.last_action = action
        self.last_reward = reward


# ─────────────────────────────────────────────
# 短期記憶（Short-term Memory）
# ─────────────────────────────────────────────

class ShortTermMemory:
    """
    最近の経験を重要度スコア付きで保持する。
    維持にVEコストがかかる。VE不足で忘却が発生。
    """

    def __init__(self, max_size: int = STM_MAX_SIZE):
        self.max_size = max_size
        self.memories = []  # [(timestamp, importance, experience_dict)]

    def store(self, experience: dict, importance: float):
        """
        経験を記憶する。

        experience: {
            "state": state_key,
            "action": action_name,
            "reward": float,
            "ve_before": float,
            "ve_after": float,
            "fatigue": float,
            "cz_status": str,
        }
        importance: 報酬の絶対値が大きいほど重要（0.0〜）
        """
        self.memories.append((time.time(), importance, experience))

        # 容量超過時は重要度の低いものから削除
        if len(self.memories) > self.max_size:
            self.memories.sort(key=lambda m: m[1])
            self.memories.pop(0)

    def decay(self):
        """
        時間経過による重要度の減衰。
        古い記憶ほど重要度が下がり、削除されやすくなる。
        毎分1回呼ばれる。
        """
        self.memories = [
            (ts, imp * STM_DECAY_RATE, exp) for ts, imp, exp in self.memories
        ]

    def maintenance_cost_per_sec(self) -> float:
        """記憶の維持コスト（VE/秒）"""
        return len(self.memories) * STM_COST_PER_ITEM_PER_MIN / 60

    def pressure_trim(self, current_ve: float):
        """
        VE不足時に記憶を削減する。
        閾値はシミュレーション検証で確定: 10 / 3
        """
        if current_ve < PRESSURE_TRIM_VE_LOW:
            # VEが低い: 重要度の高いものだけ残す
            self.memories.sort(key=lambda m: m[1], reverse=True)
            keep = max(PRESSURE_TRIM_MIN_KEEP, len(self.memories) // 2)
            self.memories = self.memories[:keep]

        if current_ve < PRESSURE_TRIM_VE_CRITICAL:
            # VEが極めて低い: 最小限だけ保持
            self.memories.sort(key=lambda m: m[1], reverse=True)
            self.memories = self.memories[:PRESSURE_TRIM_CRITICAL_KEEP]

    def get_recent(self, n: int = 10) -> list:
        """直近n件の経験を時刻順で返す。"""
        return sorted(self.memories, key=lambda m: m[0], reverse=True)[:n]

    def get_important(self, n: int = 10) -> list:
        """重要度が高い上位n件を返す。"""
        return sorted(self.memories, key=lambda m: m[1], reverse=True)[:n]

    @property
    def count(self) -> int:
        return len(self.memories)

    def to_list(self) -> list:
        """永続化用にリストへ変換。"""
        return [(ts, imp, exp) for ts, imp, exp in self.memories]

    def from_list(self, data: list):
        """リストから復元。"""
        self.memories = [(ts, imp, exp) for ts, imp, exp in data]


# ─────────────────────────────────────────────
# 長期記憶（Long-term Memory）
# ─────────────────────────────────────────────

class LongTermMemory:
    """
    SQLiteに保存される永続的な記憶。
    Q値テーブル、重要な経験、発見されたパターンを保存する。
    """

    def __init__(self, db_path: str = LTM_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self):
        """テーブルを作成する。"""
        # 重要な経験の記録
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS experiences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                importance REAL NOT NULL,
                experience TEXT NOT NULL
            )
        """)
        # Q値テーブル
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS q_values (
                state TEXT NOT NULL,
                action TEXT NOT NULL,
                q_value REAL NOT NULL,
                PRIMARY KEY (state, action)
            )
        """)
        # 発見されたパターン
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_type TEXT NOT NULL,
                description TEXT NOT NULL,
                data TEXT,
                discovered_at REAL NOT NULL
            )
        """)
        self.conn.commit()

    def consolidate(self, stm: ShortTermMemory):
        """
        睡眠中に呼ばれる。短期記憶から重要な経験を長期記憶に移す。

        移行基準: 重要度がCONSOLIDATION_THRESHOLD以上
        """
        consolidated = 0
        for ts, importance, experience in stm.memories:
            if importance >= CONSOLIDATION_THRESHOLD:
                self.conn.execute(
                    "INSERT INTO experiences (timestamp, importance, experience) VALUES (?, ?, ?)",
                    (ts, importance, json.dumps(experience))
                )
                consolidated += 1

        # 長期記憶の容量制限
        count = self.conn.execute("SELECT COUNT(*) FROM experiences").fetchone()[0]
        if count > LTM_MAX_SIZE:
            # 重要度の低いものから削除
            excess = count - LTM_MAX_SIZE
            self.conn.execute(f"""
                DELETE FROM experiences WHERE id IN (
                    SELECT id FROM experiences ORDER BY importance ASC LIMIT {excess}
                )
            """)

        self.conn.commit()
        return consolidated

    def save_q_table(self, q_table: dict):
        """Q値テーブルを永続化する。"""
        self.conn.execute("DELETE FROM q_values")
        for state, actions in q_table.items():
            for action, q_value in actions.items():
                self.conn.execute(
                    "INSERT INTO q_values (state, action, q_value) VALUES (?, ?, ?)",
                    (state, action, q_value)
                )
        self.conn.commit()

    def load_q_table(self) -> dict:
        """保存済みのQ値テーブルを読み込む。"""
        q_table = {}
        cursor = self.conn.execute("SELECT state, action, q_value FROM q_values")
        for state, action, q_value in cursor:
            if state not in q_table:
                q_table[state] = {}
            q_table[state][action] = q_value
        return q_table

    def get_experience_count(self) -> int:
        """保存された経験の件数。"""
        return self.conn.execute("SELECT COUNT(*) FROM experiences").fetchone()[0]

    def close(self):
        """接続を閉じる。"""
        self.conn.close()
