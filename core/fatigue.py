"""
Seed0 Phase 1 — 疲労（Fatigue）モジュール

疲労はVEとは独立した軸。VEが十分でも疲労は溜まる。
疲労が溜まると行動コストが増加し、最終的に「眠らざるを得ない」状態になる。
「眠れ」と命令せず、コスト構造により睡眠が最適解として浮かび上がる。

シミュレーション検証済みの確定パラメータ:
  - base_fatigue_rate: 0.0023 /秒
  - activity_fatigue_rate: 0.005 /秒（最大活動時）
  - sleep_fatigue_recovery_rate: 0.010 /秒
  - 覚醒約10時間 / 睡眠約2.4時間のサイクル
"""


# ─────────────────────────────────────────────
# 確定パラメータ
# ─────────────────────────────────────────────

# 基礎疲労蓄積率（/秒）。起きているだけで疲れる。
BASE_FATIGUE_RATE = 0.0023

# 活動による追加疲労率（/秒 × activity_level）
ACTIVITY_FATIGUE_RATE = 0.005

# 睡眠中の疲労回復率（/秒）
SLEEP_FATIGUE_RECOVERY_RATE = 0.010

# 疲労の範囲
FATIGUE_MIN = 0.0
FATIGUE_MAX = 100.0

# 強制睡眠の閾値
FORCE_SLEEP_FATIGUE = 95.0  # 疲労がこの値以上 かつ
FORCE_SLEEP_VE = 5.0         # VEがこの値以下で強制睡眠

# 起床条件
WAKE_FATIGUE_THRESHOLD = 10.0  # 疲労がこの値未満 かつ
WAKE_VE_THRESHOLD = 50.0       # VEがこの値以上で起床

# 自発的sleep行動の条件（疲労がこの値以上で意味がある）
VOLUNTARY_SLEEP_FATIGUE = 30.0


# ─────────────────────────────────────────────
# 活動レベル計算
# ─────────────────────────────────────────────

def calculate_activity_level(sensors: dict, baseline_means: dict) -> float:
    """
    現在のセンサー値がベースラインからどれだけ乖離しているか。

    0.0 = ベースラインど真ん中（アイドル状態）
    1.0 = すべての指標がベースラインから大きく乖離

    baseline_means: RunningBaselineのmeans辞書
    """
    deviations = []

    # CPU使用率: ベースラインからの乖離
    cpu = sensors.get("cpu_usage_percent") or 14
    cpu_base = baseline_means.get("cpu_usage_percent", 14.12)
    deviations.append(min(abs(cpu - cpu_base) / 30, 1.0))

    # メモリプレッシャー: ベースラインを超えた分
    mem_p = sensors.get("memory_pressure_percent") or 24
    mem_base = baseline_means.get("memory_pressure_percent", 24.38)
    deviations.append(min(max(0, mem_p - mem_base) / 20, 1.0))

    # ロードアベレージ: ベースラインを超えた分
    load = sensors.get("load_avg_1m") or 1.5
    load_base = baseline_means.get("load_avg_1m", 1.5)
    deviations.append(min(max(0, load - load_base) / 3, 1.0))

    return sum(deviations) / len(deviations) if deviations else 0.0


# ─────────────────────────────────────────────
# 疲労蓄積
# ─────────────────────────────────────────────

def calculate_fatigue_increment(dt: float, activity_level: float) -> float:
    """
    覚醒中の疲労蓄積量を計算する。

    dt: 経過秒数
    activity_level: 0.0〜1.0

    returns: 蓄積される疲労量（正の値）
    """
    return (BASE_FATIGUE_RATE + ACTIVITY_FATIGUE_RATE * activity_level) * dt


def calculate_fatigue_recovery(dt: float) -> float:
    """
    睡眠中の疲労回復量を計算する。

    returns: 回復する疲労量（正の値）
    """
    return SLEEP_FATIGUE_RECOVERY_RATE * dt


# ─────────────────────────────────────────────
# 疲労によるコスト倍率
# ─────────────────────────────────────────────

def fatigue_cost_multiplier(fatigue: float) -> float:
    """
    疲労が高いと行動のVEコストが増える。
    疲れていると同じ作業に余計なエネルギーがかかる構造。

    疲労 0〜30:  1.0倍（元気）
    疲労 30〜60: 1.0→1.5倍
    疲労 60〜85: 1.5→2.0倍
    疲労 85〜100: 2.0→3.0倍
    """
    if fatigue < 30:
        return 1.0
    elif fatigue < 60:
        return 1.0 + (fatigue - 30) / 60
    elif fatigue < 85:
        return 1.5 + (fatigue - 60) / 50
    else:
        return 2.0 + (fatigue - 85) / 15


# ─────────────────────────────────────────────
# 睡眠判定
# ─────────────────────────────────────────────

def should_force_sleep(fatigue: float, ve: float = None) -> bool:
    """強制睡眠の条件。疲労95以上で強制的に睡眠に入る。

    VE条件は撤廃。疲労の蓄積だけで睡眠が構造的に発生する。
    VE引数は後方互換のために残すが使用しない。
    """
    return fatigue >= FORCE_SLEEP_FATIGUE


def should_wake(fatigue: float, ve: float) -> bool:
    """起床条件。疲労10未満 かつ VE50以上。"""
    return fatigue < WAKE_FATIGUE_THRESHOLD and ve > WAKE_VE_THRESHOLD


def can_voluntary_sleep(fatigue: float) -> bool:
    """自発的にsleepを選んで意味がある疲労レベルか。"""
    return fatigue >= VOLUNTARY_SLEEP_FATIGUE


def clamp_fatigue(fatigue: float) -> float:
    """疲労を有効範囲に制限する。"""
    return max(FATIGUE_MIN, min(FATIGUE_MAX, fatigue))
