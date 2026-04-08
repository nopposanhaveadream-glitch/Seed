"""
Seed0 Phase 1 — 代謝（Metabolism）モジュール

仮想エネルギー（VE）の管理と基礎代謝コスト（BMC）の計算を行う。
VEはSeed0の「生命力」に相当する内部通貨。

シミュレーション検証済みの確定パラメータ:
  - base_rate: 0.01 VE/秒
  - rest_ve_recovery_rate: 0.005 VE/秒
  - sleep_ve_recovery_rate: 0.02 VE/秒
  - sleep_bmc_fraction: 0.3
"""


# ─────────────────────────────────────────────
# 確定パラメータ
# ─────────────────────────────────────────────

# 基礎代謝率（VE/秒）
BASE_RATE = 0.01

# rest行動中のVE回復率（VE/秒）。「食事」に相当。
REST_VE_RECOVERY_RATE = 0.005

# 睡眠中のVE回復率（VE/秒）
SLEEP_VE_RECOVERY_RATE = 0.02

# 睡眠中のBMC低減率（通常の30%）
SLEEP_BMC_FRACTION = 0.3

# VEの範囲
VE_MIN = 0.0
VE_MAX = 100.0


# ─────────────────────────────────────────────
# 身体ストレス倍率
# ─────────────────────────────────────────────

def body_stress_multiplier(sensors: dict) -> float:
    """
    身体の各指標が快適領域からどれだけ逸脱しているかの総合スコア。

    1.0 = 快適（追加コストなし）
    最大 4.0 = 極度のストレス（基礎代謝が4倍）

    閾値はPhase 0実測データに基づく:
      - メモリプレッシャー: 平均24%, p95=28% → 30%超でストレス
      - CPU使用率: 平均14%, p95=28% → 40%超でストレス
      - ディスク使用率: 平均28% → 70%超でストレス
    """
    stress = 0.0

    # メモリプレッシャー: 30%超で上昇、50%で+1.0
    mem_p = sensors.get("memory_pressure_percent") or 0
    if mem_p > 30:
        stress += min((mem_p - 30) / 20, 1.0)

    # CPU使用率: 40%超で上昇、70%で+1.0
    cpu = sensors.get("cpu_usage_percent") or 0
    if cpu > 40:
        stress += min((cpu - 40) / 30, 1.0)

    # ディスク使用率: 70%超で上昇、90%で+1.0
    disk = sensors.get("disk_usage_percent") or 0
    if disk > 70:
        stress += min((disk - 70) / 20, 1.0)

    return 1.0 + stress


# ─────────────────────────────────────────────
# VE計算
# ─────────────────────────────────────────────

def calculate_bmc(sensors: dict, dt: float, is_sleeping: bool = False) -> float:
    """
    基礎代謝コスト（BMC）を計算する。

    sensors: 現在のセンサー値
    dt: 経過秒数
    is_sleeping: 睡眠中かどうか

    returns: 消費されるVE量（正の値）
    """
    if is_sleeping:
        # 睡眠中は通常の30%のBMC
        return BASE_RATE * SLEEP_BMC_FRACTION * dt
    else:
        # 覚醒中はストレス倍率を適用
        bsm = body_stress_multiplier(sensors)
        return BASE_RATE * bsm * dt


def calculate_rest_recovery(dt: float) -> float:
    """
    rest行動中のVE回復量。「食事」に相当。
    restを選んでいる間だけ回復する。

    returns: 回復するVE量（正の値）
    """
    return REST_VE_RECOVERY_RATE * dt


def calculate_sleep_recovery(dt: float) -> float:
    """
    睡眠中のVE回復量。restより高速。

    returns: 回復するVE量（正の値）
    """
    return SLEEP_VE_RECOVERY_RATE * dt


def clamp_ve(ve: float) -> float:
    """VEを有効範囲に制限する。"""
    return max(VE_MIN, min(VE_MAX, ve))
