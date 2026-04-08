"""
Seed0 Phase 1 — エージェント（Agent）メインループ

Seed0の心臓部。5秒間隔で以下のループを繰り返す:
  1. SENSE（感知）: センサー読取、baseline更新
  2. METABOLIZE（代謝計算）: 無意識プロセス
  3. DECIDE（行動選択）: 意識プロセス
  4. ACT（行動実行）: 選択された行動を実行
  5. EVALUATE（評価）: 報酬計算、記憶
  6. DECAY（状態劣化）: 定期保存

起動: python3 -m core.agent
"""

import sys
import os
import time
import signal
import json
import logging

# プロジェクトルートをパスに追加
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from phase0.sensors import read_all_sensors
from core.state import AgentState
from core.unconscious import UnconsciousProcess
from core.conscious import ConsciousProcess
from core.comfort_zone import evaluate_comfort_zone


# ─────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────

# メインループの間隔（秒）
LOOP_INTERVAL = 5.0

# ステータス表示の間隔（秒）
STATUS_DISPLAY_INTERVAL = 60

# ログ設定
LOG_DIR = os.path.expanduser("~/.seed0/logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(LOG_DIR, "agent.log"),
            encoding="utf-8"
        ),
    ]
)
logger = logging.getLogger("seed0")


# ─────────────────────────────────────────────
# Seed0 エージェント
# ─────────────────────────────────────────────

class Seed0Agent:
    """Seed0の本体。メインループを回す。"""

    def __init__(self, use_sudo: bool = False, resume: bool = True):
        """
        use_sudo: powermetricsにsudoを使うか
        resume: 前回の状態から復帰するか
        """
        self.use_sudo = use_sudo
        self.state = AgentState()
        self.unconscious = UnconsciousProcess()
        self.conscious = ConsciousProcess()
        self._running = False
        self._last_status_time = 0

        # 状態の復元または初期化
        if resume and self.state.load():
            logger.info("前回の状態から復帰しました")
            logger.info(f"  VE={self.state.ve:.1f}, 疲労={self.state.fatigue:.1f}, "
                        f"ステップ={self.state.total_steps}")
        else:
            self.state.initialize(cold_start_from_db=True)
            logger.info("新規初期化（Cold Start）")

        # Q値テーブルを共有
        self.conscious.selector = self.state.action_selector

    def run(self):
        """メインループを開始する。"""
        self._running = True
        logger.info("=" * 50)
        logger.info("Seed0 Phase 1 起動")
        logger.info(f"  ループ間隔: {LOOP_INTERVAL}秒")
        logger.info(f"  sudo: {'あり' if self.use_sudo else 'なし'}")
        logger.info("=" * 50)

        # シグナルハンドラ（安全な終了用）
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        try:
            while self._running:
                loop_start = time.time()
                self._tick()

                # ステータス表示
                now = time.time()
                if now - self._last_status_time >= STATUS_DISPLAY_INTERVAL:
                    self._display_status()
                    self._last_status_time = now

                # 定期保存
                if self.state.should_save():
                    self.state.save()

                # 次のステップまで待つ（0.5秒刻みで中断チェック）
                elapsed = time.time() - loop_start
                remaining = max(0, LOOP_INTERVAL - elapsed)
                sleep_end = time.time() + remaining
                while time.time() < sleep_end and self._running:
                    time.sleep(0.5)

        except Exception as e:
            logger.error(f"エラー: {e}", exc_info=True)
        finally:
            self._shutdown()

    def _tick(self):
        """1ステップの処理。"""
        self.state.step()
        dt = LOOP_INTERVAL

        # === 1. SENSE（感知）===
        sensors = read_all_sensors(use_sudo=self.use_sudo)

        # 即時記憶にbefore値を記録
        self.state.immediate_memory.record_before(sensors)

        # 前回のセンサー値を保存
        self.state.prev_sensors = self.state.latest_sensors
        self.state.latest_sensors = sensors

        # === 2. METABOLIZE（代謝計算）=== 無意識プロセス
        self.unconscious.tick(self.state, sensors, dt)

        # comfort zone状態を更新
        self.state.comfort_zone_status = evaluate_comfort_zone(
            self.state.baseline, sensors
        )

        # === 3-5. DECIDE → ACT → EVALUATE === 意識プロセス
        # 次のセンサー値がないので、前回のセンサー値との差分で評価
        chosen = self.conscious.think_and_act(
            self.state, sensors, self.state.prev_sensors, dt
        )

        # ログ出力（デバッグレベル）
        if self.state.total_steps % 12 == 0:  # 1分に1回
            logger.debug(
                f"step={self.state.total_steps} "
                f"VE={self.state.ve:.1f} F={self.state.fatigue:.1f} "
                f"action={chosen} cz={self.state.comfort_zone_status}"
            )

    def _display_status(self):
        """ステータスを表示する。"""
        s = self.state.get_status_dict()
        sleeping_str = "💤 睡眠中" if s["is_sleeping"] else "👁 覚醒中"
        cz_str = {"normal": "🟢", "alert": "🟡", "emergency": "🔴"}.get(
            s["cz_status"], "⚪"
        )

        # 行動統計
        top_actions = sorted(
            self.state.total_actions.items(), key=lambda x: -x[1]
        )[:3]
        action_str = ", ".join(f"{a}:{c}" for a, c in top_actions)

        logger.info(
            f"{sleeping_str} | VE={s['ve']:.1f} | 疲労={s['fatigue']:.1f} | "
            f"CZ={cz_str} | 記憶={s['stm_count']} | "
            f"ε={s['epsilon']:.3f} | step={s['total_steps']} | "
            f"稼働{s['uptime_h']:.1f}h | 行動: {action_str}"
        )

    def _signal_handler(self, signum, frame):
        """安全な終了を行う。"""
        logger.info(f"シグナル {signum} を受信。終了処理を開始...")
        self._running = False

    def _shutdown(self):
        """終了処理。状態を保存して閉じる。"""
        logger.info("終了処理中...")

        # 状態を保存
        self.state.save()
        logger.info("  状態を保存しました")

        # Q値テーブルを長期記憶に保存
        self.state.long_term_memory.save_q_table(
            self.state.action_selector.q_table
        )
        logger.info("  Q値テーブルを保存しました")

        # 長期記憶を閉じる
        self.state.long_term_memory.close()
        logger.info("  長期記憶を閉じました")

        logger.info("Seed0 Phase 1 終了")


# ─────────────────────────────────────────────
# エントリーポイント
# ─────────────────────────────────────────────

def main():
    """コマンドライン引数を処理してSeed0を起動する。"""
    import argparse
    parser = argparse.ArgumentParser(description="Seed0 Phase 1 — 代謝AI")
    parser.add_argument("--sudo", action="store_true",
                        help="powermetricsにsudoを使用する")
    parser.add_argument("--no-resume", action="store_true",
                        help="前回の状態から復帰せず新規初期化する")
    parser.add_argument("--status", action="store_true",
                        help="現在の状態を表示して終了")
    parser.add_argument("--debug", action="store_true",
                        help="デバッグログを有効にする")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger("seed0").setLevel(logging.DEBUG)

    if args.status:
        # 状態表示モード
        state = AgentState()
        if state.load():
            s = state.get_status_dict()
            print(json.dumps(s, indent=2, ensure_ascii=False))
        else:
            print("保存された状態がありません")
        return

    # Seed0を起動
    agent = Seed0Agent(
        use_sudo=args.sudo,
        resume=not args.no_resume,
    )
    agent.run()


if __name__ == "__main__":
    main()
