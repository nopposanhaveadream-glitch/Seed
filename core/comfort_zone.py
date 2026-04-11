"""
Seed0 Phase 1 — 快適領域（Comfort Zone）モジュール

comfort zoneは人間が定義しない。Seed0が統計的に自己発見する。
指数移動平均（EMA）で各センサー値の「自分の普通」を追跡し、
逸脱度（deviation_score）で状態を判定する。

シミュレーション検証済みの確定パラメータ:
  - alpha: 0.001（約1.5時間で環境変化に適応）
"""

import sqlite3
import os


# ─────────────────────────────────────────────
# 確定パラメータ
# ─────────────────────────────────────────────

# EMAの平滑化係数。0.001 → 最近の約1000サンプル（≈83分）の重み付き平均
DEFAULT_ALPHA = 0.001

# comfort zone判定の状態
STATUS_NORMAL = "normal"
STATUS_ALERT = "alert"
STATUS_EMERGENCY = "emergency"

# Cold Start時に初期値を持つセンサーキー（Phase 0 実測データに基づく）
# 新しいセンサーキーは初回データから自動的にbaselineに取り込まれる
COLD_START_KEYS = [
    "memory_pressure_percent",
    "cpu_usage_percent",
    "disk_usage_percent",
    "memory_used_mb",
    "memory_compressed_mb",
    "process_count",
    "load_avg_1m",
]

# Cold Start 初期値（Phase 0 実測データに基づく）
COLD_START_BASELINE = {
    "cpu_usage_percent":        {"mean": 14.12, "variance": 38.32},
    "memory_pressure_percent":  {"mean": 24.38, "variance": 9.49},
    "memory_used_mb":           {"mean": 14443, "variance": 464000},
    "memory_compressed_mb":     {"mean": 3830,  "variance": 370000},
    "disk_usage_percent":       {"mean": 28.0,  "variance": 1.0},
    "process_count":            {"mean": 872,   "variance": 144},
    "load_avg_1m":              {"mean": 1.5,   "variance": 0.5},
}


# ─────────────────────────────────────────────
# RunningBaseline（EMAベースの自己発見）
# ─────────────────────────────────────────────

class RunningBaseline:
    """
    指数移動平均（EMA）で各センサー値の「自分の普通」を追跡する。
    新しいデータほど重みが大きい = 環境の変化に適応する。
    """

    def __init__(self, alpha: float = DEFAULT_ALPHA):
        self.alpha = alpha
        self.means = {}      # 各センサーのEMA平均
        self.variances = {}  # 各センサーのEMA分散
        self._initialized = False

    def cold_start(self):
        """
        Phase 0データでbaselineを初期化する。
        「教えている」のではなく「初期条件を与えている」。
        経験を積むにつれて上書きされる。
        """
        for key, vals in COLD_START_BASELINE.items():
            self.means[key] = vals["mean"]
            self.variances[key] = vals["variance"]
        self._initialized = True

    def cold_start_from_db(self, db_path: str = "~/.seed0/phase0/body_data.db"):
        """
        Phase 0のデータベースから直接統計値を計算して初期化する。
        データベースが存在しない場合はハードコードされた初期値を使う。
        新しいセンサー（Phase 0にないもの）は初回データから自動的に学習開始する。
        """
        db_path = os.path.expanduser(db_path)
        if not os.path.exists(db_path):
            self.cold_start()
            return

        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            for key in COLD_START_KEYS:
                cur.execute(f"""
                    SELECT AVG({key}), AVG(({key} - sub.m) * ({key} - sub.m))
                    FROM body_sensor_readings,
                         (SELECT AVG({key}) as m FROM body_sensor_readings) sub
                    WHERE {key} IS NOT NULL
                """)
                row = cur.fetchone()
                if row and row[0] is not None:
                    self.means[key] = row[0]
                    self.variances[key] = row[1] if row[1] else 0.0
            conn.close()
            self._initialized = True
        except Exception:
            # DBエラー時はハードコード値で初期化
            self.cold_start()

    def update(self, key: str, value: float):
        """新しいセンサー値で「自分の普通」を更新する。"""
        if value is None:
            return

        if key not in self.means:
            # 初回: そのまま採用
            self.means[key] = value
            self.variances[key] = 0.0
            return

        # EMA更新
        old_mean = self.means[key]
        new_mean = old_mean + self.alpha * (value - old_mean)
        new_var = (1 - self.alpha) * (
            self.variances[key] + self.alpha * (value - old_mean) ** 2
        )

        self.means[key] = new_mean
        self.variances[key] = new_var

    def update_from_sensors(self, sensors: dict):
        """
        センサー辞書の全数値キーをまとめて更新する。
        新しいセンサーキーが来ても自動的にbaselineに取り込む。
        どのセンサーを追跡するかをハードコードしない（第一原則）。
        """
        for key, val in sensors.items():
            if val is not None and isinstance(val, (int, float)):
                self.update(key, val)

    def deviation_score(self, key: str, value: float) -> float:
        """
        現在の値が「自分の普通」からどれだけ逸脱しているか。

        0.0 = 普通のど真ん中
        1.0 = comfort zone の境界（2σ）
        >1.0 = comfort zone の外（異常）
        """
        if key not in self.means or self.variances.get(key, 0) == 0:
            return 0.0

        stddev = self.variances[key] ** 0.5
        if stddev < 0.001:
            return 0.0

        return abs(value - self.means[key]) / (2.0 * stddev)

    def get_comfort_zone(self, key: str, sigma: float = 2.0) -> tuple:
        """comfort zoneの範囲 (lower, upper) を返す。"""
        if key not in self.means:
            return (None, None)
        mean = self.means[key]
        stddev = self.variances.get(key, 0) ** 0.5
        return (mean - sigma * stddev, mean + sigma * stddev)

    def to_dict(self) -> dict:
        """永続化用に辞書へ変換する。"""
        return {
            "alpha": self.alpha,
            "means": dict(self.means),
            "variances": dict(self.variances),
        }

    def from_dict(self, data: dict):
        """辞書から復元する。"""
        self.alpha = data.get("alpha", DEFAULT_ALPHA)
        self.means = data.get("means", {})
        self.variances = data.get("variances", {})
        self._initialized = True


# ─────────────────────────────────────────────
# 状態判定
# ─────────────────────────────────────────────

def evaluate_comfort_zone(baseline: RunningBaseline, sensors: dict) -> str:
    """
    全センサー値のdeviation_scoreの最大値に基づいて状態を判定する。
    baselineが追跡している全キーを評価対象にする。

    returns: "normal" | "alert" | "emergency"
    """
    max_deviation = 0.0
    for key, val in sensors.items():
        if val is not None and isinstance(val, (int, float)):
            score = baseline.deviation_score(key, val)
            max_deviation = max(max_deviation, score)

    if max_deviation < 1.0:
        return STATUS_NORMAL
    elif max_deviation < 2.0:
        return STATUS_ALERT
    else:
        return STATUS_EMERGENCY
