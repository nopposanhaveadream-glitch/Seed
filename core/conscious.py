"""
Seed0 Phase 1 — 意識プロセス（Conscious Process）

Seed0が「考えて」実行する処理。行動選択と評価に相当する。
無意識プロセスの後に実行される。

Q学習（epsilon-greedy）による行動選択:
  - 状態を離散化
  - 実行可能な行動からQ値最大の行動を選択（epsilonの確率で探索）
  - 報酬はcomfort zoneへの接近/離脱のみ
  - 「正しい行動」は教えない
"""

import random
import time

from core import metabolism, fatigue
from core.actions import (
    ACTIONS, get_available_actions, get_effective_cost, execute_action
)
from core.comfort_zone import RunningBaseline, evaluate_comfort_zone


# ─────────────────────────────────────────────
# Q学習による行動選択
# ─────────────────────────────────────────────

class ActionSelector:
    """
    状態 × 行動のQ値テーブルに基づいて行動を選択する。
    epsilon-greedy方策。
    """

    def __init__(self, learning_rate: float = 0.1, discount: float = 0.95,
                 epsilon: float = 0.3, epsilon_min: float = 0.05,
                 epsilon_decay: float = 0.9999):
        self.lr = learning_rate
        self.gamma = discount
        self.epsilon = epsilon
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.q_table = {}

    def discretize_state(self, ve: float, fat: float,
                          cz_status: str, sensors: dict) -> str:
        """
        連続値の内部状態を離散的な状態キーに変換する。
        状態空間が大きすぎると学習が進まないので粗く離散化する。
        """
        # VE: low / mid / high
        ve_l = "low" if ve < 30 else ("mid" if ve < 70 else "high")

        # 疲労: low / mid / high / critical
        f_l = ("low" if fat < 30 else "mid" if fat < 60
               else "high" if fat < 85 else "critical")

        # メモリプレッシャー: low / mid / high
        mem_p = sensors.get("memory_pressure_percent") or 0
        mem_l = "low" if mem_p < 25 else ("mid" if mem_p < 35 else "high")

        # CPU: low / mid / high
        cpu = sensors.get("cpu_usage_percent") or 0
        cpu_l = "low" if cpu < 20 else ("mid" if cpu < 50 else "high")

        return f"{ve_l}_{f_l}_{cz_status}_{mem_l}_{cpu_l}"

    def select_action(self, state: str, available: list) -> str:
        """epsilon-greedy方策で行動を選択する。"""
        if not available:
            return "rest"

        # 探索: ランダム
        if random.random() < self.epsilon:
            return random.choice(available)

        # 活用: Q値最大の行動
        if state not in self.q_table:
            self.q_table[state] = {}

        best_action = None
        best_q = float("-inf")
        for action in available:
            q = self.q_table[state].get(action, 0.0)
            if q > best_q:
                best_q = q
                best_action = action

        return best_action if best_action else random.choice(available)

    def update(self, state: str, action: str, reward: float, next_state: str):
        """
        Q学習の更新式:
        Q(s,a) ← Q(s,a) + α [r + γ max_a' Q(s',a') - Q(s,a)]
        """
        if state not in self.q_table:
            self.q_table[state] = {}
        if next_state not in self.q_table:
            self.q_table[next_state] = {}

        old_q = self.q_table[state].get(action, 0.0)
        next_max = (max(self.q_table[next_state].values())
                    if self.q_table[next_state] else 0.0)
        new_q = old_q + self.lr * (reward + self.gamma * next_max - old_q)
        self.q_table[state][action] = new_q

    def decay_epsilon(self):
        """epsilonを減衰させる。"""
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)


# ─────────────────────────────────────────────
# 報酬計算
# ─────────────────────────────────────────────

def calculate_reward(before: dict, after: dict,
                     baseline: RunningBaseline, ve_cost: float) -> float:
    """
    行動の前後でcomfort zoneとの距離がどう変化したかを評価する。
    「正しい行動」は教えない。comfort zoneへの接近/離脱のみ。

    before: 行動前のセンサー値
    after: 行動後のセンサー値
    baseline: RunningBaseline
    ve_cost: 行動に使ったVEコスト
    """
    delta = 0.0
    count = 0

    keys = ["memory_pressure_percent", "cpu_usage_percent", "disk_usage_percent"]
    for key in keys:
        bv = before.get(key)
        av = after.get(key)
        if bv is not None and av is not None:
            bd = baseline.deviation_score(key, bv)
            ad = baseline.deviation_score(key, av)
            # comfort zoneに近づいた → 正、離れた → 負
            delta += (bd - ad)
            count += 1

    if count == 0:
        return 0.0

    # 平均逸脱変化を報酬に変換
    comfort_reward = delta / count

    # VEコストのペナルティ
    cost_penalty = ve_cost * 0.05

    return comfort_reward - cost_penalty


# ─────────────────────────────────────────────
# 意識プロセス本体
# ─────────────────────────────────────────────

class ConsciousProcess:
    """
    行動の選択と実行。メインループのDECIDE〜EVALUATE部分。
    """

    def __init__(self):
        self.selector = ActionSelector()

    def think_and_act(self, state, sensors: dict, next_sensors: dict,
                       dt: float) -> str:
        """
        1ステップ分の意識プロセスを実行する。

        state: AgentState
        sensors: 現在のセンサー値
        next_sensors: 次のステップのセンサー値（報酬計算用、実環境では1ステップ後に評価）
        dt: 経過秒数

        returns: 選択された行動名
        """
        # 睡眠中は行動選択しない
        if state.is_sleeping:
            return "sleeping"

        now = time.time()
        cz_status = evaluate_comfort_zone(state.baseline, sensors)

        # 実行可能な行動を列挙
        available = get_available_actions(
            state.ve, state.fatigue, state.action_cooldowns, now
        )

        if not available:
            return "blocked"

        # 状態を離散化
        state_key = self.selector.discretize_state(
            state.ve, state.fatigue, cz_status, sensors
        )

        # 行動選択
        chosen = self.selector.select_action(state_key, available)

        # 行動のVEコストを消費
        eff_cost = get_effective_cost(chosen, state.fatigue)
        state.ve = metabolism.clamp_ve(state.ve - eff_cost)

        # クールダウンを記録
        state.action_cooldowns[chosen] = now

        # 行動の実行
        result = execute_action(chosen)

        # rest行動の特殊処理: VE回復（食事）+ BMC軽減リベート
        if chosen == "rest":
            ve_gain = metabolism.calculate_rest_recovery(dt, sensors)
            state.ve = metabolism.clamp_ve(state.ve + ve_gain)

        # sleep行動の処理
        if chosen == "sleep" and fatigue.can_voluntary_sleep(state.fatigue):
            state.fall_asleep()

        # 報酬計算とQ学習更新
        if next_sensors:
            reward = calculate_reward(
                sensors, next_sensors, state.baseline, eff_cost
            )
            next_cz = evaluate_comfort_zone(state.baseline, next_sensors)
            next_key = self.selector.discretize_state(
                state.ve, state.fatigue, next_cz, next_sensors
            )
            self.selector.update(state_key, chosen, reward, next_key)
        else:
            reward = 0.0

        # epsilonの減衰
        self.selector.decay_epsilon()

        # 経験を記憶に記録
        experience = {
            "state": state_key,
            "action": chosen,
            "reward": reward,
            "ve": state.ve,
            "fatigue": state.fatigue,
            "cz_status": cz_status,
        }
        importance = abs(reward)
        state.short_term_memory.store(experience, importance)

        # 即時記憶を更新
        state.immediate_memory.record_after(sensors, chosen, reward)

        # 統計を更新
        state.total_actions[chosen] = state.total_actions.get(chosen, 0) + 1

        return chosen
