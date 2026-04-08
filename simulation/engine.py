"""
Seed0 Phase 1 シミュレーションエンジン

Phase 0の実データをリプレイし、代謝構造のパラメータが
「壊れない」かどうかを検証する。

目的: 壊れない構造を見つける（良い振る舞いを学習させるのではない）
"""

import math
import random
import sqlite3
import os
from dataclasses import dataclass, field
from typing import Optional


# ─────────────────────────────────────────────
# Phase 0 データローダー
# ─────────────────────────────────────────────

def load_phase0_data(db_path: str = "~/.seed0/phase0/body_data.db") -> list:
    """
    Phase 0のSQLiteデータベースから全レコードを読み込む。
    各レコードはセンサー値の辞書として返す。
    """
    db_path = os.path.expanduser(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT timestamp, memory_pressure_percent, cpu_usage_percent,
               disk_usage_percent, disk_free_gb, load_avg_1m,
               memory_used_mb, memory_compressed_mb, process_count,
               net_connections
        FROM body_sensor_readings
        ORDER BY id
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ─────────────────────────────────────────────
# 仮想エネルギー（VE）と代謝
# ─────────────────────────────────────────────

def body_stress_multiplier(sensors: dict) -> float:
    """身体ストレス倍率。1.0（快適）〜 4.0（極度のストレス）"""
    stress = 0.0
    mem_p = sensors.get("memory_pressure_percent") or 0
    if mem_p > 30:
        stress += min((mem_p - 30) / 20, 1.0)
    cpu = sensors.get("cpu_usage_percent") or 0
    if cpu > 40:
        stress += min((cpu - 40) / 30, 1.0)
    disk = sensors.get("disk_usage_percent") or 0
    if disk > 70:
        stress += min((disk - 70) / 20, 1.0)
    return 1.0 + stress


# ─────────────────────────────────────────────
# 疲労
# ─────────────────────────────────────────────

def fatigue_cost_multiplier(fatigue: float) -> float:
    """疲労による行動コスト倍率"""
    if fatigue < 30:
        return 1.0
    elif fatigue < 60:
        return 1.0 + (fatigue - 30) / 60
    elif fatigue < 85:
        return 1.5 + (fatigue - 60) / 50
    else:
        return 2.0 + (fatigue - 85) / 15


# ─────────────────────────────────────────────
# Running Baseline（comfort zone 自己発見）
# ─────────────────────────────────────────────

class RunningBaseline:
    """指数移動平均（EMA）で「自分の普通」を追跡する"""

    def __init__(self, alpha: float = 0.001):
        self.alpha = alpha
        self.means = {}
        self.variances = {}

    def update(self, key: str, value: float):
        if value is None:
            return
        if key not in self.means:
            self.means[key] = value
            self.variances[key] = 0.0
            return
        old_mean = self.means[key]
        new_mean = old_mean + self.alpha * (value - old_mean)
        new_var = (1 - self.alpha) * (
            self.variances[key] + self.alpha * (value - old_mean) ** 2
        )
        self.means[key] = new_mean
        self.variances[key] = new_var

    def deviation_score(self, key: str, value: float) -> float:
        if key not in self.means or self.variances.get(key, 0) == 0:
            return 0.0
        stddev = self.variances[key] ** 0.5
        if stddev < 0.001:
            return 0.0
        return abs(value - self.means[key]) / (2.0 * stddev)

    def get_stats(self, key: str) -> tuple:
        """(mean, stddev) を返す"""
        m = self.means.get(key, 0)
        v = self.variances.get(key, 0)
        return (m, v ** 0.5)


# ─────────────────────────────────────────────
# 行動
# ─────────────────────────────────────────────

@dataclass
class Action:
    name: str
    ve_cost: float
    cooldown_sec: float

ACTIONS = {
    "sense_body":       Action("sense_body", 0.1, 3),
    "sense_deep":       Action("sense_deep", 0.5, 30),
    "purge_memory":     Action("purge_memory", 1.0, 300),
    "clean_temp":       Action("clean_temp", 2.0, 600),
    "adjust_priority":  Action("adjust_priority", 0.5, 60),
    "write_memory":     Action("write_memory", 0.3, 10),
    "rest":             Action("rest", 0.0, 0),
    "sleep":            Action("sleep", 0.5, 0),
}


# ─────────────────────────────────────────────
# Q学習による行動選択
# ─────────────────────────────────────────────

class ActionSelector:
    def __init__(self, lr: float = 0.1, discount: float = 0.95,
                 epsilon: float = 0.3, epsilon_min: float = 0.05,
                 epsilon_decay: float = 0.9999):
        self.lr = lr
        self.gamma = discount
        self.epsilon = epsilon
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.q_table = {}

    def discretize_state(self, ve: float, fatigue: float,
                          cz_status: str, sensors: dict) -> str:
        ve_l = "low" if ve < 30 else ("mid" if ve < 70 else "high")
        f_l = ("low" if fatigue < 30 else "mid" if fatigue < 60
               else "high" if fatigue < 85 else "critical")
        mem_p = sensors.get("memory_pressure_percent") or 0
        mem_l = "low" if mem_p < 25 else ("mid" if mem_p < 35 else "high")
        cpu = sensors.get("cpu_usage_percent") or 0
        cpu_l = "low" if cpu < 20 else ("mid" if cpu < 50 else "high")
        return f"{ve_l}_{f_l}_{cz_status}_{mem_l}_{cpu_l}"

    def select_action(self, state: str, available: list) -> str:
        if not available:
            return "rest"
        if random.random() < self.epsilon:
            return random.choice(available)
        if state not in self.q_table:
            self.q_table[state] = {}
        best_a, best_q = None, float("-inf")
        for a in available:
            q = self.q_table[state].get(a, 0.0)
            if q > best_q:
                best_q = q
                best_a = a
        return best_a if best_a else random.choice(available)

    def update(self, state: str, action: str, reward: float, next_state: str):
        if state not in self.q_table:
            self.q_table[state] = {}
        if next_state not in self.q_table:
            self.q_table[next_state] = {}
        old_q = self.q_table[state].get(action, 0.0)
        next_max = max(self.q_table[next_state].values()) if self.q_table[next_state] else 0.0
        new_q = old_q + self.lr * (reward + self.gamma * next_max - old_q)
        self.q_table[state][action] = new_q

    def decay_epsilon(self):
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)


# ─────────────────────────────────────────────
# 短期記憶
# ─────────────────────────────────────────────

class ShortTermMemory:
    def __init__(self, max_size: int = 500):
        self.max_size = max_size
        self.memories = []  # [(importance, data)]

    def store(self, importance: float, data: dict):
        self.memories.append((importance, data))
        if len(self.memories) > self.max_size:
            self.memories.sort(key=lambda m: m[0])
            self.memories.pop(0)

    def decay(self, rate: float = 0.999):
        self.memories = [(imp * rate, d) for imp, d in self.memories]

    def maintenance_cost_per_sec(self) -> float:
        """VE/秒 での維持コスト"""
        return len(self.memories) * 0.001 / 60

    def pressure_trim(self, ve: float):
        """VE不足時に記憶を削減"""
        if ve < 20:
            self.memories.sort(key=lambda m: m[0], reverse=True)
            keep = max(50, len(self.memories) // 2)
            self.memories = self.memories[:keep]
        if ve < 5:
            self.memories.sort(key=lambda m: m[0], reverse=True)
            self.memories = self.memories[:20]

    @property
    def count(self):
        return len(self.memories)


# ─────────────────────────────────────────────
# シミュレーション状態
# ─────────────────────────────────────────────

@dataclass
class SimState:
    """シミュレーション中のSeed0の全状態"""
    ve: float = 100.0
    fatigue: float = 0.0
    is_sleeping: bool = False

    # パラメータ（テストごとに変更可能）
    base_rate: float = 0.01
    base_fatigue_rate: float = 0.0023
    activity_fatigue_rate: float = 0.005
    sleep_ve_recovery_rate: float = 0.02
    sleep_bmc_fraction: float = 0.3
    sleep_fatigue_recovery_rate: float = 0.014
    rest_ve_recovery_rate: float = 0.005  # rest行動選択時のVE回復率（VE/秒）

    # 内部
    baseline: RunningBaseline = field(default_factory=RunningBaseline)
    stm: ShortTermMemory = field(default_factory=ShortTermMemory)
    selector: ActionSelector = field(default_factory=ActionSelector)
    action_cooldowns: dict = field(default_factory=dict)
    step_count: int = 0

    # ログ
    ve_log: list = field(default_factory=list)
    fatigue_log: list = field(default_factory=list)
    sleep_log: list = field(default_factory=list)  # [(start_step, end_step)]
    action_log: list = field(default_factory=list)
    memory_count_log: list = field(default_factory=list)
    cz_status_log: list = field(default_factory=list)

    # 睡眠追跡
    _sleep_start: Optional[int] = None


def comfort_zone_status(baseline: RunningBaseline, sensors: dict) -> str:
    max_dev = 0.0
    for key in ["memory_pressure_percent", "cpu_usage_percent", "disk_usage_percent"]:
        val = sensors.get(key)
        if val is not None:
            score = baseline.deviation_score(key, val)
            max_dev = max(max_dev, score)
    if max_dev < 1.0:
        return "normal"
    elif max_dev < 2.0:
        return "alert"
    else:
        return "emergency"


def calculate_reward(before: dict, after: dict, baseline: RunningBaseline,
                     ve_cost: float) -> float:
    delta = 0.0
    count = 0
    for key in ["memory_pressure_percent", "cpu_usage_percent", "disk_usage_percent"]:
        bv = before.get(key)
        av = after.get(key)
        if bv is not None and av is not None:
            bd = baseline.deviation_score(key, bv)
            ad = baseline.deviation_score(key, av)
            delta += (bd - ad)
            count += 1
    if count == 0:
        return 0.0
    return delta / count - ve_cost * 0.05


# ─────────────────────────────────────────────
# メインシミュレーションループ
# ─────────────────────────────────────────────

def run_simulation(sensor_data: list, state: SimState,
                   max_steps: Optional[int] = None,
                   enable_actions: bool = True,
                   enable_sleep: bool = True) -> SimState:
    """
    Phase 0データをリプレイしてシミュレーションを実行する。

    sensor_data: Phase 0のセンサーデータリスト
    state: 初期状態
    max_steps: 実行するステップ数の上限（Noneなら全件）
    enable_actions: 行動選択を有効にするか
    enable_sleep: 睡眠/回復を有効にするか
    """
    dt = 5.0  # 5秒間隔
    steps = min(len(sensor_data) - 1, max_steps or len(sensor_data) - 1)
    decay_counter = 0

    for i in range(steps):
        sensors = sensor_data[i]
        next_sensors = sensor_data[i + 1]
        state.step_count += 1

        # === 無意識プロセス ===

        if state.is_sleeping and enable_sleep:
            # 睡眠中: VE回復・疲労回復
            sleep_bmc = state.base_rate * state.sleep_bmc_fraction * dt
            ve_recovery = state.sleep_ve_recovery_rate * dt
            state.ve = min(100.0, state.ve - sleep_bmc + ve_recovery)
            state.fatigue = max(0.0, state.fatigue - state.sleep_fatigue_recovery_rate * dt)

            # 起床判定
            if state.fatigue < 10.0 and state.ve > 50.0:
                state.is_sleeping = False
                if state._sleep_start is not None:
                    state.sleep_log.append((state._sleep_start, state.step_count))
                    state._sleep_start = None
        else:
            # 覚醒中: BMC消費
            bsm = body_stress_multiplier(sensors)
            bmc = state.base_rate * bsm * dt
            state.ve = max(0.0, state.ve - bmc)

            # 疲労蓄積
            activity = 0.0
            cpu = sensors.get("cpu_usage_percent") or 14
            mem_p = sensors.get("memory_pressure_percent") or 24
            load = sensors.get("load_avg_1m") or 1.5
            activity += min(abs(cpu - 14) / 30, 1.0)
            activity += min(max(0, mem_p - 24) / 20, 1.0)
            activity += min(max(0, load - 1.5) / 3, 1.0)
            activity /= 3.0

            f_inc = (state.base_fatigue_rate + state.activity_fatigue_rate * activity) * dt
            state.fatigue = min(100.0, state.fatigue + f_inc)

            # 記憶維持コスト
            mem_cost = state.stm.maintenance_cost_per_sec() * dt
            state.ve = max(0.0, state.ve - mem_cost)

            # 記憶減衰（60秒ごと）
            decay_counter += dt
            if decay_counter >= 60:
                state.stm.decay()
                decay_counter = 0

            # 記憶圧縮
            state.stm.pressure_trim(state.ve)

            # 強制睡眠チェック
            if state.fatigue >= 95 and state.ve < 5 and enable_sleep:
                state.is_sleeping = True
                state._sleep_start = state.step_count

        # baseline更新
        for key in ["memory_pressure_percent", "cpu_usage_percent", "disk_usage_percent"]:
            val = sensors.get(key)
            if val is not None:
                state.baseline.update(key, val)

        cz = comfort_zone_status(state.baseline, sensors)
        state.cz_status_log.append(cz)

        # === 意識プロセス（行動選択）===
        if enable_actions and not state.is_sleeping:
            # 実行可能な行動を列挙
            available = []
            now_step = state.step_count * dt
            for name, action in ACTIONS.items():
                eff_cost = action.ve_cost * fatigue_cost_multiplier(state.fatigue)
                if state.ve < eff_cost:
                    continue
                last = state.action_cooldowns.get(name, 0)
                if now_step - last < action.cooldown_sec:
                    continue
                available.append(name)

            if available:
                st_key = state.selector.discretize_state(
                    state.ve, state.fatigue, cz, sensors
                )
                chosen = state.selector.select_action(st_key, available)
                action = ACTIONS[chosen]
                eff_cost = action.ve_cost * fatigue_cost_multiplier(state.fatigue)
                state.ve = max(0.0, state.ve - eff_cost)
                state.action_cooldowns[chosen] = now_step

                # rest行動の処理: VE回復（食事に相当）
                if chosen == "rest":
                    ve_gain = state.rest_ve_recovery_rate * dt
                    state.ve = min(100.0, state.ve + ve_gain)

                # 睡眠行動の処理
                if chosen == "sleep" and enable_sleep and state.fatigue > 30:
                    state.is_sleeping = True
                    state._sleep_start = state.step_count

                # 報酬計算とQ学習更新
                reward = calculate_reward(sensors, next_sensors, state.baseline, eff_cost)
                next_cz = comfort_zone_status(state.baseline, next_sensors)
                next_key = state.selector.discretize_state(
                    state.ve, state.fatigue, next_cz, next_sensors
                )
                state.selector.update(st_key, chosen, reward, next_key)
                state.selector.decay_epsilon()

                # 記憶に記録
                importance = abs(reward)
                state.stm.store(importance, {"action": chosen, "reward": reward})

                state.action_log.append(chosen)
            else:
                state.action_log.append("blocked")
        elif state.is_sleeping:
            state.action_log.append("sleeping")
        else:
            state.action_log.append("none")

        # ログ記録
        state.ve_log.append(state.ve)
        state.fatigue_log.append(state.fatigue)
        state.memory_count_log.append(state.stm.count)

    return state
