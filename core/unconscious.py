"""
Seed0 Phase 1 — 無意識プロセス（Unconscious Process）

常に自動実行される身体維持プロセス。
Seed0が「考えなくても」勝手に進む処理。
メインループの各ステップで意識プロセスの前に必ず呼ばれる。

処理内容:
  - 基礎代謝コスト（VE消費）
  - 疲労蓄積
  - 記憶維持コスト
  - 記憶減衰（60秒ごと）
  - 記憶圧縮（VE不足時）
  - baseline更新
  - 強制睡眠チェック
  - 睡眠中のVE回復・疲労回復
"""

from core import metabolism, fatigue
from core.comfort_zone import RunningBaseline


class UnconsciousProcess:
    """
    自動的に実行される身体維持プロセス。

    毎ステップ tick() が呼ばれ、内部状態を更新する。
    state オブジェクト（AgentState）を直接変更する。
    """

    def __init__(self):
        self._decay_counter = 0.0  # 記憶減衰のタイマー（秒）

    def tick(self, state, sensors: dict, dt: float):
        """
        1ステップ分の無意識プロセスを実行する。

        state: AgentState（全内部状態への参照、直接変更する）
        sensors: 現在のセンサー値
        dt: 前回からの経過秒数
        """
        if state.is_sleeping:
            self._tick_sleeping(state, dt)
        else:
            self._tick_waking(state, sensors, dt)

        # baseline更新（覚醒・睡眠問わず常に実行）
        state.baseline.update_from_sensors(sensors)

    def _tick_sleeping(self, state, dt: float):
        """睡眠中の無意識プロセス。"""

        # 1. 睡眠中のBMC消費（通常の30%）
        bmc = metabolism.calculate_bmc({}, dt, is_sleeping=True)
        state.ve = metabolism.clamp_ve(state.ve - bmc)

        # 2. 睡眠中のVE回復
        ve_recovery = metabolism.calculate_sleep_recovery(dt)
        state.ve = metabolism.clamp_ve(state.ve + ve_recovery)

        # 3. 疲労回復
        fat_recovery = fatigue.calculate_fatigue_recovery(dt)
        state.fatigue = fatigue.clamp_fatigue(state.fatigue - fat_recovery)

        # 4. 起床判定
        if fatigue.should_wake(state.fatigue, state.ve):
            state.wake_up()

    def _tick_waking(self, state, sensors: dict, dt: float):
        """覚醒中の無意識プロセス。"""

        # 1. 基礎代謝コスト
        bmc = metabolism.calculate_bmc(sensors, dt, is_sleeping=False)
        state.ve = metabolism.clamp_ve(state.ve - bmc)

        # 2. 疲労蓄積
        activity = fatigue.calculate_activity_level(
            sensors, state.baseline.means
        )
        fat_inc = fatigue.calculate_fatigue_increment(dt, activity)
        state.fatigue = fatigue.clamp_fatigue(state.fatigue + fat_inc)

        # 3. 記憶維持コスト
        mem_cost = state.short_term_memory.maintenance_cost_per_sec() * dt
        state.ve = metabolism.clamp_ve(state.ve - mem_cost)

        # 4. 記憶減衰（60秒ごと）
        self._decay_counter += dt
        if self._decay_counter >= 60:
            state.short_term_memory.decay()
            self._decay_counter = 0

        # 5. 記憶圧縮（VE不足時）
        state.short_term_memory.pressure_trim(state.ve)

        # 6. 強制睡眠チェック
        if fatigue.should_force_sleep(state.fatigue, state.ve):
            state.fall_asleep()
