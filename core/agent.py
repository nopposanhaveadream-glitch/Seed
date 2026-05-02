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
import datetime
import atexit
import fcntl

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

# PIDファイル（二重起動防止）
PID_FILE = os.path.expanduser("~/.seed0/agent.pid")

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
# プロセス重複防止（PIDファイル + flock）
# ─────────────────────────────────────────────
#
# 二重起動防止は `fcntl.flock(LOCK_EX | LOCK_NB)` を ~/.seed0/agent.pid に
# 対して取得する方式を採用している。
#
# flock を採用する理由（事実確認に基づく）:
#   - kernel が fd 解放時に自動的にロックを解放する
#     → SIGKILL / segfault / 電源断でも残留しない（POSIX flock(2) 仕様）
#   - ロックの取得自体が原子的（TOCTOU の解消）
#   - PID 値の照合が不要（生存中のプロセスがロックを保持しているため、
#     PID 再利用問題は構造的に発生しない）
#
# 詳細は以下のレポートを参照:
#   - ~/.seed0/reports/pid_bypass_investigation_2026-05-02.md
#   - ~/.seed0/reports/flock_failure_mode_analysis_2026-05-02.md
#
# 注意: PID ファイルへの書き込みは ftruncate + write で行う。
# atomic rename（tempfile + os.rename）は使わない。flock は inode に紐付くため、
# rename で別 inode に置換するとロックが path から外れて、別プロセスから
# 取得可能になってしまう（実測で確認済み、上記レポート C-3 関連）。


def acquire_pid_lock(pid_path: str = PID_FILE):
    """
    PIDファイルに排他ロック（flock LOCK_EX | LOCK_NB）を取得する。

    返り値:
      - 成功時: ロック保持中のファイルディスクリプタ（int）。**呼出側は
        プロセス寿命の間このfdを保持し続ける必要がある**。close すると
        flock が解放されて二重起動防止が無効になる。
      - 失敗時（既に他プロセスがロック保持）: None

    挙動:
      - O_CREAT | O_RDWR でPIDファイルを open
      - flock(LOCK_EX | LOCK_NB) を試行
      - 取得失敗（BlockingIOError / OSError EWOULDBLOCK） → fdをcloseして
        None を返す（既存PIDも情報目的で読み出しログに含める）
      - 取得成功 → ftruncate(0) + write で現プロセスのPIDを書き込み、
        FD_CLOEXEC を設定（subprocess経由でのfd漏洩を防ぐ）、fdを返す
    """
    os.makedirs(os.path.dirname(pid_path), exist_ok=True)

    fd = os.open(pid_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        # ロック取得失敗 → 他プロセスが保持中
        # 既存PID値を情報目的で読み出す（ロック判定には使わない）
        try:
            with open(pid_path, "r") as f:
                old_pid_str = f.read().strip() or "?"
        except Exception:
            old_pid_str = "?"
        try:
            os.close(fd)
        except OSError:
            pass
        logger.error(
            f"Seed0は既に動作中です（PID {old_pid_str}）。"
            f"二重起動を防止しました。"
        )
        return None

    # ロック取得成功 → FD_CLOEXEC を立てて、fork+exec した子に漏れないようにする
    try:
        flags = fcntl.fcntl(fd, fcntl.F_GETFD)
        fcntl.fcntl(fd, fcntl.F_SETFD, flags | fcntl.FD_CLOEXEC)
    except OSError as e:
        logger.warning(f"FD_CLOEXEC設定失敗: {e}")

    # PIDをファイルに書き込む（ftruncate + write、rename は使わない）
    try:
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
    except OSError as e:
        logger.warning(f"PID書き込み失敗（ロックは取得済み）: {e}")

    return fd


def release_pid_lock(fd, pid_path: str = PID_FILE):
    """
    PIDロックを明示的に解放してファイルを削除する。冪等。

    fd: acquire_pid_lock() が返した値（None も許容）
    pid_path: PIDファイルのパス

    SIGKILL / 電源断などの異常終了経路では、kernel がfdを自動close
    することで flock を解放するため、本関数を呼べなくても二重起動防止
    の安全性は保たれる。本関数は正常終了経路での明示的な解放と、
    PIDファイルの削除のために使う。
    """
    if fd is not None and isinstance(fd, int) and fd >= 0:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            # 既に解放済み or fd 無効。kernelが解放するので問題なし
            pass
        try:
            os.close(fd)
        except OSError:
            # 既に close 済み
            pass
    try:
        if os.path.exists(pid_path):
            os.remove(pid_path)
    except OSError as e:
        logger.warning(f"PIDファイル削除失敗: {e}")


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
        self._current_date = datetime.date.today()
        self._last_action = "none"  # ビューア用
        # ── 構造化ステップトレース（step_trace.jsonl）用 ──
        # 既存agent.logと併走する分析向けログ。1ステップ=1行JSON。
        self._step_trace_path = os.path.join(LOG_DIR, "step_trace.jsonl")
        self._step_trace_file = None  # run()内で開く
        self._prev_step_ve = None     # 前ステップ終了時VE（interstepΔ計算用）

        # ── 二重起動防止のflockロック保持用 ──
        # acquire_pid_lock() が返したfdを保持。プロセス寿命の間 close しない。
        self._pid_lock_fd = None
        self._pid_released = False  # release_pid_lock呼出を冪等にするためのフラグ

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
        # 二重起動防止チェック（flockベース）
        self._pid_lock_fd = acquire_pid_lock()
        if self._pid_lock_fd is None:
            sys.exit(1)
        # 異常終了時にもPIDファイルを削除する（fdは kernel が自動close → flock解放）
        atexit.register(self._release_pid_lock_idempotent)

        # ── 構造化ステップトレースの出力ファイルを開く（追記、行バッファ） ──
        # 失敗してもエージェントは止めない（既存agent.log側は別ハンドラで稼働継続）
        try:
            self._step_trace_file = open(
                self._step_trace_path, "a", encoding="utf-8", buffering=1
            )
        except Exception as e:
            logger.warning(f"step_trace.jsonl を開けません: {e}")
            self._step_trace_file = None

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
        was_sleeping = self.state.is_sleeping
        self.unconscious.tick(self.state, sensors, dt)

        # 睡眠/覚醒の切り替わりを検知してログ出力
        if was_sleeping and not self.state.is_sleeping:
            logger.info(
                f"☀️ 起床 | VE={self.state.ve:.1f} | 疲労={self.state.fatigue:.1f} | "
                f"step={self.state.total_steps}"
            )

        # comfort zone状態を更新
        prev_cz = self.state.comfort_zone_status
        self.state.comfort_zone_status = evaluate_comfort_zone(
            self.state.baseline, sensors
        )
        # comfort zone状態の変化をログ出力
        if prev_cz != self.state.comfort_zone_status:
            cz_icon = {"normal": "🟢", "alert": "🟡", "emergency": "🔴"}.get(
                self.state.comfort_zone_status, "⚪"
            )
            logger.info(
                f"CZ変化: {prev_cz} → {self.state.comfort_zone_status} {cz_icon} | "
                f"VE={self.state.ve:.1f} | step={self.state.total_steps}"
            )

        # === 3-5. DECIDE → ACT → EVALUATE === 意識プロセス
        # 次のセンサー値がないので、前回のセンサー値との差分で評価
        ve_before = self.state.ve
        chosen = self.conscious.think_and_act(
            self.state, sensors, self.state.prev_sensors, dt
        )
        ve_after = self.state.ve

        # 入眠の検知
        if not was_sleeping and self.state.is_sleeping:
            logger.info(
                f"💤 入眠 | VE={self.state.ve:.1f} | 疲労={self.state.fatigue:.1f} | "
                f"step={self.state.total_steps}"
            )

        # 最新の行動を記録（ビューア用）
        self._last_action = chosen

        # 毎ステップの行動ログ（INFOレベル）
        reward = self.state.immediate_memory.last_reward
        logger.info(
            f"[{self.state.total_steps:>6}] "
            f"{chosen:<16} | "
            f"VE={ve_after:5.1f} (Δ{ve_after - ve_before:+.2f}) | "
            f"疲労={self.state.fatigue:5.1f} | "
            f"報酬={reward:+.4f} | "
            f"CZ={self.state.comfort_zone_status} | "
            f"記憶={self.state.short_term_memory.count}"
        )

        # ── 構造化ステップトレース（step_trace.jsonl） ──
        # 既存agent.logとは別ファイルに、決定時の全情報を1行JSONで追記する。
        # 失敗してもエージェントを止めない。
        self._write_step_trace(chosen, ve_before, ve_after, reward)
        # 次回ステップのinterstepΔ計算のため、ステップ末VEを保存
        self._prev_step_ve = ve_after

    def _write_step_trace(self, chosen: str, ve_before: float,
                           ve_after: float, reward: float):
        """構造化ステップトレースを step_trace.jsonl に1行追記する。"""
        if self._step_trace_file is None:
            return

        decision = self.conscious.last_step_trace
        eps = decision.get("epsilon")

        trace = {
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "step": self.state.total_steps,
            "action": chosen,
            "ve": round(ve_after, 4),
            "fatigue": round(self.state.fatigue, 4),
            "ve_before": round(ve_before, 4),
            "ve_after": round(ve_after, 4),
            "ve_delta_step": round(ve_after - ve_before, 4),
            "ve_delta_interstep": (
                round(ve_after - self._prev_step_ve, 4)
                if self._prev_step_ve is not None else None
            ),
            "reward": round(reward, 6) if reward is not None else None,
            "memory_count": self.state.short_term_memory.count,
            "cz_status": self.state.comfort_zone_status,
            "state_key": decision.get("state_key"),
            "state_components": decision.get("state_components"),
            "sensors_raw": decision.get("sensors_raw"),
            "exploration": decision.get("exploration"),
            "epsilon": round(eps, 6) if eps is not None else None,
            "q_values": decision.get("q_values"),
            "chosen_q_value": decision.get("chosen_q_value"),
            "available_actions": decision.get("available_actions"),
        }

        try:
            self._step_trace_file.write(
                json.dumps(trace, ensure_ascii=False) + "\n"
            )
        except Exception as e:
            # トレース失敗でエージェントは止めない
            logger.warning(f"step_trace書込失敗: {e}")

    def _display_status(self):
        """60秒ごとのステータスサマリーを表示する。"""
        s = self.state.get_status_dict()
        sleeping_str = "💤 睡眠中" if s["is_sleeping"] else "👁 覚醒中"
        cz_str = {"normal": "🟢", "alert": "🟡", "emergency": "🔴"}.get(
            s["cz_status"], "⚪"
        )

        # 行動統計（全行動）
        all_actions = sorted(
            self.state.total_actions.items(), key=lambda x: -x[1]
        )
        action_str = ", ".join(f"{a}:{c}" for a, c in all_actions)

        # Q値テーブルのサイズ
        q_states = len(self.state.action_selector.q_table)
        q_entries = sum(
            len(actions) for actions in self.state.action_selector.q_table.values()
        )

        logger.info(
            f"\n{'─' * 60}\n"
            f"  {sleeping_str} | step={s['total_steps']} | 稼働{s['uptime_h']:.1f}h\n"
            f"  VE={s['ve']:.1f} | 疲労={s['fatigue']:.1f} | CZ={cz_str} {s['cz_status']}\n"
            f"  記憶={s['stm_count']}件 | ε={s['epsilon']:.3f} | "
            f"Q値={q_states}状態/{q_entries}エントリ\n"
            f"  睡眠={s['sleep_count']}回 | 行動: {action_str}\n"
            f"{'─' * 60}"
        )

        # ステータスJSON書き出し（ビューア用、atomic write）
        try:
            status_data = {
                "timestamp": time.time(),
                "display": {
                    "ve": round(s["ve"], 1),
                    "fatigue": round(s["fatigue"], 1),
                    "is_sleeping": s["is_sleeping"],
                    "cz_status": s["cz_status"],
                },
                "stats": {
                    "memory_count": s["stm_count"],
                    "q_states": q_states,
                    "q_entries": q_entries,
                    "epsilon": round(s["epsilon"], 4),
                    "total_steps": s["total_steps"],
                    "current_action": self._last_action,
                    "sleep_count": s["sleep_count"],
                    "uptime_hours": round(s["uptime_h"], 1),
                },
            }
            status_path = os.path.expanduser("~/.seed0/status.json")
            tmp_path = status_path + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(status_data, f)
            os.replace(tmp_path, status_path)
        except Exception:
            pass  # ビューアのためにエージェントを止めない

        # 日次レポート生成（日付が変わったら前日分を出力）
        today = datetime.date.today()
        if today != self._current_date:
            self._generate_daily_report(self._current_date)
            self._current_date = today

    def _generate_daily_report(self, report_date: datetime.date):
        """日次レポートを生成する。失敗してもエージェントは停止しない。"""
        try:
            from core.daily_report import generate
            target = report_date.isoformat()
            log_path = os.path.join(LOG_DIR, "agent.log")
            path = generate(target, log_path)
            logger.info(f"📊 日次レポート生成完了: {path}")
        except Exception as e:
            logger.warning(f"日次レポート生成失敗: {e}")

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

        # 構造化ステップトレースのファイルを閉じる
        if self._step_trace_file is not None:
            try:
                self._step_trace_file.close()
                logger.info("  step_trace.jsonl を閉じました")
            except Exception as e:
                logger.warning(f"step_trace.jsonl close失敗: {e}")
            self._step_trace_file = None

        # PIDロック解放 + PIDファイル削除（冪等）
        self._release_pid_lock_idempotent()

        logger.info("Seed0 Phase 1 終了")

    def _release_pid_lock_idempotent(self):
        """flockロック解放とPIDファイル削除。冪等（atexitと_shutdownの両経路から呼ばれる）。"""
        if self._pid_released:
            return
        self._pid_released = True
        release_pid_lock(self._pid_lock_fd, PID_FILE)
        self._pid_lock_fd = None


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
