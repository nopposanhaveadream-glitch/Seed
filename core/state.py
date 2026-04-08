"""
Seed0 Phase 1 — エージェント状態（AgentState）

Seed0の全内部状態を統合管理するクラス。
全モジュールがこの状態を参照・変更する。
定期的にSQLiteに永続化し、プロセス再起動時に復帰できる。
"""

import json
import os
import sqlite3
import time

from core.metabolism import VE_MAX
from core.comfort_zone import RunningBaseline
from core.memory import ImmediateMemory, ShortTermMemory, LongTermMemory
from core.conscious import ActionSelector


# ─────────────────────────────────────────────
# 永続化用データベースパス
# ─────────────────────────────────────────────

STATE_DB_PATH = os.path.expanduser("~/.seed0/state/agent_state.db")

# 状態保存の間隔（秒）
SAVE_INTERVAL = 60


class AgentState:
    """Seed0の全内部状態を保持する。"""

    def __init__(self):
        # === エネルギー ===
        self.ve = VE_MAX  # 起動時は満タン

        # === 疲労 ===
        self.fatigue = 0.0
        self.is_sleeping = False

        # === 快適領域 ===
        self.baseline = RunningBaseline()

        # === 記憶 ===
        self.immediate_memory = ImmediateMemory()
        self.short_term_memory = ShortTermMemory()
        self.long_term_memory = LongTermMemory()

        # === 行動選択 ===
        self.action_selector = ActionSelector()
        self.action_cooldowns = {}  # {action_name: last_used_timestamp}

        # === センサー ===
        self.latest_sensors = {}
        self.prev_sensors = {}

        # === comfort zone ===
        self.comfort_zone_status = "normal"

        # === 統計 ===
        self.total_steps = 0
        self.total_actions = {}  # {action_name: count}
        self.uptime_start = time.time()

        # === 睡眠追跡 ===
        self._sleep_start_time = None
        self.sleep_log = []  # [(start_time, end_time, duration_sec)]

        # === 永続化 ===
        self._last_save_time = time.time()

    def initialize(self, cold_start_from_db: bool = True):
        """
        初期化。Cold Startでbaselineを設定する。

        cold_start_from_db: TrueならPhase 0のDBから統計値を計算。
                           Falseならハードコードの初期値を使う。
        """
        if cold_start_from_db:
            self.baseline.cold_start_from_db()
        else:
            self.baseline.cold_start()

        # 長期記憶からQ値テーブルを復元
        q_table = self.long_term_memory.load_q_table()
        if q_table:
            self.action_selector.q_table = q_table

    def fall_asleep(self):
        """睡眠に入る。"""
        if not self.is_sleeping:
            self.is_sleeping = True
            self._sleep_start_time = time.time()

    def wake_up(self):
        """睡眠から起きる。起床時に記憶整理を行う。"""
        if self.is_sleeping:
            self.is_sleeping = False
            end_time = time.time()

            # 睡眠ログを記録
            if self._sleep_start_time is not None:
                duration = end_time - self._sleep_start_time
                self.sleep_log.append(
                    (self._sleep_start_time, end_time, duration)
                )
                self._sleep_start_time = None

            # 睡眠中の記憶整理: 短期記憶→長期記憶へ統合
            consolidated = self.long_term_memory.consolidate(
                self.short_term_memory
            )

            # Q値テーブルを永続化
            self.long_term_memory.save_q_table(
                self.action_selector.q_table
            )

            # 短期記憶をクリア（統合されなかったものも含めて）
            self.short_term_memory.memories.clear()

    def step(self):
        """ステップカウントを進める。"""
        self.total_steps += 1

    def uptime_seconds(self) -> float:
        """起動からの経過秒数。"""
        return time.time() - self.uptime_start

    def should_save(self) -> bool:
        """状態を保存すべきタイミングか。"""
        return time.time() - self._last_save_time >= SAVE_INTERVAL

    # ─────────────────────────────────────────
    # 永続化
    # ─────────────────────────────────────────

    def save(self):
        """全状態をSQLiteに保存する。"""
        os.makedirs(os.path.dirname(STATE_DB_PATH), exist_ok=True)
        conn = sqlite3.connect(STATE_DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
        """)

        now = time.time()
        state_data = {
            "ve": self.ve,
            "fatigue": self.fatigue,
            "is_sleeping": self.is_sleeping,
            "baseline": self.baseline.to_dict(),
            "action_cooldowns": self.action_cooldowns,
            "total_steps": self.total_steps,
            "total_actions": self.total_actions,
            "uptime_start": self.uptime_start,
            "sleep_log": self.sleep_log,
            "epsilon": self.action_selector.epsilon,
            "stm": self.short_term_memory.to_list(),
        }

        conn.execute(
            "INSERT OR REPLACE INTO agent_state (key, value, updated_at) VALUES (?, ?, ?)",
            ("state", json.dumps(state_data), now)
        )
        conn.commit()
        conn.close()

        self._last_save_time = now

    def load(self) -> bool:
        """
        保存された状態をSQLiteから復元する。

        returns: 復元に成功したらTrue
        """
        if not os.path.exists(STATE_DB_PATH):
            return False

        try:
            conn = sqlite3.connect(STATE_DB_PATH)
            cursor = conn.execute(
                "SELECT value FROM agent_state WHERE key = 'state'"
            )
            row = cursor.fetchone()
            conn.close()

            if not row:
                return False

            data = json.loads(row[0])

            self.ve = data.get("ve", VE_MAX)
            self.fatigue = data.get("fatigue", 0.0)
            self.is_sleeping = data.get("is_sleeping", False)

            # baseline復元
            baseline_data = data.get("baseline")
            if baseline_data:
                self.baseline.from_dict(baseline_data)

            self.action_cooldowns = data.get("action_cooldowns", {})
            self.total_steps = data.get("total_steps", 0)
            self.total_actions = data.get("total_actions", {})
            self.uptime_start = data.get("uptime_start", time.time())
            self.sleep_log = data.get("sleep_log", [])

            # epsilon復元
            epsilon = data.get("epsilon")
            if epsilon is not None:
                self.action_selector.epsilon = epsilon

            # 短期記憶復元
            stm_data = data.get("stm")
            if stm_data:
                self.short_term_memory.from_list(stm_data)

            # Q値テーブル復元
            q_table = self.long_term_memory.load_q_table()
            if q_table:
                self.action_selector.q_table = q_table

            return True

        except Exception:
            return False

    def get_status_dict(self) -> dict:
        """現在の状態をサマリ辞書として返す。ログ表示用。"""
        return {
            "ve": round(self.ve, 2),
            "fatigue": round(self.fatigue, 2),
            "is_sleeping": self.is_sleeping,
            "cz_status": self.comfort_zone_status,
            "stm_count": self.short_term_memory.count,
            "total_steps": self.total_steps,
            "epsilon": round(self.action_selector.epsilon, 4),
            "uptime_h": round(self.uptime_seconds() / 3600, 2),
            "sleep_count": len(self.sleep_log),
        }
