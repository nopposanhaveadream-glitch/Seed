"""
Seed0 Phase 1 — 行動プリミティブ（Actions）モジュール

Seed0に与えるのは「何ができるか」の一覧だけ。
「いつ」「なぜ」それをするかはSeed0自身が発見する。

Phase 1（環境1: 自分の身体だけが見える世界）では、
身体の維持に関する最小限の8つの行動を定義する。
"""

import os
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

from core.fatigue import fatigue_cost_multiplier


# ─────────────────────────────────────────────
# 行動定義
# ─────────────────────────────────────────────

@dataclass
class Action:
    """Seed0が実行できる一つの行動。"""
    name: str           # 行動名
    ve_cost: float      # 基本VEコスト
    cooldown_sec: float # 連続実行を防ぐ冷却時間（秒）
    description: str    # 行動の説明


# 8つの行動プリミティブ
ACTIONS = {
    # === 感覚系（情報収集） ===
    # 現在はno-op（実際のセンサー読取はメインループで毎ステップ実行）。
    # 将来、行動固有のリソース消費が実装されたら実測値に基づきコストを設定する。
    "sense_body": Action(
        name="sense_body",
        ve_cost=0.0,
        cooldown_sec=3,
        description="全センサーを読み取り内部状態を更新する",
    ),

    "sense_deep": Action(
        name="sense_deep",
        ve_cost=0.0,
        cooldown_sec=30,
        description="powermetrics等の重いコマンドで詳細な身体検査を行う",
    ),

    # === 維持系（自己代謝） ===
    # purge_memory: 短期記憶を整理する（重要度の低いものから20%削減）
    # 「忘れる」手段を構造として与える。使うかどうかはSeed0が決める。
    "purge_memory": Action(
        name="purge_memory",
        ve_cost=0.004,
        cooldown_sec=60,
        description="短期記憶を整理する。重要度の低い記憶から20%を削減する",
    ),

    # clean_temp: ファイル削除。CPU 14μs（BMC基準で0.001 VE）
    "clean_temp": Action(
        name="clean_temp",
        ve_cost=0.001,
        cooldown_sec=600,
        description="一時ファイル・ログを削除しディスク容量を回復する",
    ),

    # adjust_priority: 現在はno-op相当（os.nice 1回）
    "adjust_priority": Action(
        name="adjust_priority",
        ve_cost=0.0,
        cooldown_sec=60,
        description="自身のプロセス優先度を調整する",
    ),

    # === 記憶系 ===
    # write_memoryを選んだときだけSTMに経験が記録される。
    # 行動自体のコストは0。記憶の維持コスト（STM_COST）が間接的にVEを消費する。
    "write_memory": Action(
        name="write_memory",
        ve_cost=0.0,
        cooldown_sec=10,
        description="現在の経験を短期記憶に記録する",
    ),

    # === 休息系 ===
    "rest": Action(
        name="rest",
        ve_cost=0.0,
        cooldown_sec=0,
        description="休憩（食事）。VEを回復する",
    ),

    # sleep: 眠ること自体にエネルギーは不要。疲労≥30でのみ選択可能。
    "sleep": Action(
        name="sleep",
        ve_cost=0.0,
        cooldown_sec=0,
        description="睡眠モードに移行。VE高速回復・疲労回復・記憶整理",
    ),

    # === 自己診断系 ===
    "diagnose": Action(
        name="diagnose",
        ve_cost=0.0,
        cooldown_sec=60,
        description="全センサー値とbaseline比較で総合評価を行う",
    ),
}


# ─────────────────────────────────────────────
# 行動の実行可否チェック
# ─────────────────────────────────────────────

def get_effective_cost(action_name: str, fatigue: float) -> float:
    """疲労を考慮した実効VEコストを計算する。"""
    action = ACTIONS.get(action_name)
    if action is None:
        return float("inf")
    return action.ve_cost * fatigue_cost_multiplier(fatigue)


def is_action_available(action_name: str, ve: float, fatigue: float,
                         cooldowns: dict, current_time: float) -> bool:
    """
    指定の行動が実行可能かどうかを判定する。

    ve: 現在のVE
    fatigue: 現在の疲労値
    cooldowns: {action_name: last_used_timestamp}
    current_time: 現在時刻（time.time()）
    """
    action = ACTIONS.get(action_name)
    if action is None:
        return False

    # VEチェック（疲労コスト倍率を考慮）
    eff_cost = get_effective_cost(action_name, fatigue)
    if ve < eff_cost:
        return False

    # クールダウンチェック
    last_used = cooldowns.get(action_name, 0)
    if current_time - last_used < action.cooldown_sec:
        return False

    # sleep行動は疲労が一定以上でないと選択不可
    # （疲労不足で眠れないのにVEだけ消費する無駄を防ぐ）
    if action_name == "sleep":
        from core.fatigue import VOLUNTARY_SLEEP_FATIGUE
        if fatigue < VOLUNTARY_SLEEP_FATIGUE:
            return False

    return True


def get_available_actions(ve: float, fatigue: float,
                           cooldowns: dict, current_time: float) -> list:
    """実行可能な全行動のリストを返す。"""
    available = []
    for name in ACTIONS:
        if is_action_available(name, ve, fatigue, cooldowns, current_time):
            available.append(name)
    return available


# ─────────────────────────────────────────────
# 行動の実行（実際のシステムコマンド）
# ─────────────────────────────────────────────

def _run_cmd(cmd: str, timeout: int = 10) -> Optional[str]:
    """シェルコマンドを実行して結果を返す。失敗時はNone。"""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout if result.returncode == 0 else None
    except Exception:
        return None


def execute_action(action_name: str) -> dict:
    """
    行動を実際に実行する。

    returns: {
        "success": bool,
        "effect": str,  # 何が起きたかの説明
    }
    """
    if action_name == "sense_body":
        # sensors.pyのread_all_sensors()は呼び出し元が行うので、
        # ここでは「実行した」という記録だけ
        return {"success": True, "effect": "センサー読取を実行"}

    elif action_name == "sense_deep":
        # powermetricsを使った詳細検査（sudo不要な範囲で）
        return {"success": True, "effect": "詳細センサー読取を実行"}

    elif action_name == "purge_memory":
        # STMの記憶削減は呼び出し元（conscious.py）が処理する
        return {"success": True, "effect": "短期記憶を整理"}

    elif action_name == "clean_temp":
        # Seed0自身が作った一時ファイルの削除
        # 安全のため、~/.seed0/tmp/ のみ対象
        tmp_dir = os.path.expanduser("~/.seed0/tmp")
        if os.path.exists(tmp_dir):
            import shutil
            try:
                # 中身だけ削除（ディレクトリは残す）
                for item in os.listdir(tmp_dir):
                    path = os.path.join(tmp_dir, item)
                    if os.path.isfile(path):
                        os.remove(path)
                return {"success": True, "effect": f"一時ファイルを削除"}
            except Exception as e:
                return {"success": False, "effect": f"削除失敗: {e}"}
        return {"success": True, "effect": "一時ファイルなし"}

    elif action_name == "adjust_priority":
        # 自プロセスのnice値を上げる（優先度を下げて「遠慮」する）
        try:
            pid = os.getpid()
            os.nice(1)  # 優先度を1段階下げる
            return {"success": True, "effect": f"プロセス{pid}の優先度を下げた"}
        except Exception:
            return {"success": True, "effect": "優先度調整スキップ"}

    elif action_name == "write_memory":
        # 記憶の書き込みは呼び出し元が行う
        return {"success": True, "effect": "経験を記憶に記録"}

    elif action_name == "rest":
        # 何もしない。VE回復は呼び出し元が処理する。
        return {"success": True, "effect": "休憩（VE回復中）"}

    elif action_name == "sleep":
        # 睡眠モードへの移行は呼び出し元が処理する
        return {"success": True, "effect": "睡眠モードに移行"}

    elif action_name == "diagnose":
        # 自己診断は呼び出し元がcomfort_zone評価で行う
        return {"success": True, "effect": "自己診断を実行"}

    else:
        return {"success": False, "effect": f"未知の行動: {action_name}"}
