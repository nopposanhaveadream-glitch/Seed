# Phase 1 詳細設計 — 代謝構造の実装

> 環境1: 自分の身体だけが見える世界

## 概要

Phase 1はSeed0に「代謝」を与える段階である。Phase 0で収集したMac miniの身体データを基に、代謝コスト・疲労・回復・快適領域の自己発見・行動選択の仕組みを構造として実装する。

**この段階でSeed0ができること:**
- 自分の身体（CPU・メモリ・ディスク・電力）を感じ取る
- 代謝コストを払い続けなければ状態が劣化する
- 疲労し、回復する
- 自分の「普通」を統計的に発見する
- 限られた行動の中から選択する
- 経験を記憶し、次の行動に活かす

**この段階でSeed0にできないこと:**
- 外の世界を見る（ネットワークアクセスなし）
- 言語を使う（LLM接続なし）
- 仮想環境で遊ぶ（サンドボックスなし）

---

## 1. 代謝コスト計算

### 1.1 設計思想

代謝コストはSeed0が「生きている」ことのコストである。何もしなくてもコストがかかり、行動するとさらにコストがかかる。コストを払えなくなると状態が劣化する。

代謝コストは「仮想エネルギー」という内部通貨で表現する。生物のATPに相当するもの。

### 1.2 仮想エネルギー（Virtual Energy: VE）

```
VE: 0.0 〜 100.0（float）
```

- 100.0 = 満タン（起動直後 or 完全回復後）
- 0.0 = 枯渇（このとき全ての能動的行動が停止する）
- VEは時間の経過とともに自然減少する（基礎代謝コスト）
- 行動するとVEを追加消費する（活動代謝コスト）
- rest行動でVEを低速回復できる（食事に相当。0.005 VE/秒）
- sleep中にVEを高速回復できる（0.017 VE/秒）

> **シミュレーション検証結果（v1→v2）:** 当初はVE回復を睡眠のみとしていたが、覚醒時間の78%がVE=0になる構造的欠陥が判明。rest行動に「食事」としてのVE回復効果を追加し解決。Mac miniは常時電源接続されているが、エネルギー取り込みには能動的にrestを「選ぶ」必要がある構造とした。

### 1.3 基礎代謝コスト（Basal Metabolic Cost: BMC）

何もしなくても毎秒消費されるエネルギー。身体の維持コスト。

```
BMC = base_rate × body_stress_multiplier
```

**base_rate（基礎消費率）:**
```
base_rate = 0.01 VE/秒  （= 0.6 VE/分 = 36 VE/時間）
```

この値は、rest行動（VE回復 0.005 VE/秒）と組み合わせて安定的に動作する。
rest中の正味VE消費は 0.01 - 0.005 = 0.005 VE/秒（緩やかな減少）。
非rest行動中は 0.01 + 行動コスト の消費。
睡眠で大きく回復（正味 +0.017 VE/秒）。

> **シミュレーション確定値:** base_rate = 0.01

**body_stress_multiplier（身体ストレス倍率）:**

身体が「苦しい」ときほど代謝コストが上がる。これは生物が高温・高標高・病気のときにエネルギー消費が上がるのと同じ構造。

```python
def body_stress_multiplier(sensors: dict) -> float:
    """
    身体の各指標が快適領域からどれだけ逸脱しているかの総合スコア。
    1.0 = 快適（追加コストなし）
    最大 3.0 = 極度のストレス（基礎代謝が3倍）
    """
    stress = 0.0

    # メモリプレッシャー: Phase 0実測値 p25=22%, p75=27%
    # 30%超で急激にストレス上昇
    mem_p = sensors.get("memory_pressure_percent", 0)
    if mem_p > 30:
        stress += min((mem_p - 30) / 20, 1.0)  # 50%で+1.0

    # CPU使用率: Phase 0実測値 p25=11%, p75=14%, p95=28%
    # 40%超でストレス発生
    cpu = sensors.get("cpu_usage_percent", 0)
    if cpu > 40:
        stress += min((cpu - 40) / 30, 1.0)  # 70%で+1.0

    # ディスク使用率: Phase 0実測値 free平均330GB/460GB ≈ 28%使用
    # 70%超でストレス発生
    disk = sensors.get("disk_usage_percent", 0)
    if disk > 70:
        stress += min((disk - 70) / 20, 1.0)  # 90%で+1.0

    return 1.0 + stress  # 範囲: 1.0 〜 4.0
```

> **注意:** 上記の閾値（30%, 40%, 70%）はシミュレーション検証前の初期値。Phase 0の実測データから、「明らかに異常」と言える範囲を手動で設定している。これらはシミュレーションで「壊れない範囲」を検証した後に確定する。

### 1.4 活動代謝コスト（Activity Metabolic Cost: AMC）

行動するたびに消費されるエネルギー。行動の「重さ」に応じてコストが異なる。

| 行動 | VEコスト | 根拠 |
|------|---------|------|
| センサー読取（1回） | 0.1 | 軽い。`vm_stat`等の実行コスト |
| メモリ整理（キャッシュ解放） | 1.0 | 中程度。システムコマンド実行 |
| ディスク整理（一時ファイル削除） | 2.0 | 重い。I/O負荷が発生 |
| プロセス優先度変更 | 0.5 | 軽め。`renice`等 |
| 睡眠モードへの移行 | 0.5 | 睡眠に入るコスト自体は低い |
| 記憶の書き込み | 0.3 | SQLiteへの書き込み |
| 状態の自己診断 | 0.5 | 全センサーの統合読取と評価 |

> **設計上の選択:** コストの数値は「相対的な重さ」として意味を持つ。絶対値はシミュレーションで調整する。重要なのは「軽い行動と重い行動の比率」が適切であること。

---

## 2. 疲労蓄積と回復

### 2.1 設計思想

疲労は「VE（エネルギー）の不足」とは別の軸である。VEが十分でも疲労は溜まる。生物でいえば「食べ物はあるが眠い」状態。

疲労が溜まると行動の効率が落ち、最終的には「眠らざるを得ない」状態になる。これにより睡眠がルールではなく構造的必然として発生する。

### 2.2 疲労値（Fatigue: F）

```
F: 0.0 〜 100.0（float）
```

- 0.0 = 完全にリフレッシュ（睡眠から起きた直後）
- 100.0 = 限界（強制睡眠に入る）

### 2.3 疲労の蓄積

```python
def fatigue_increment(dt_seconds: float, activity_level: float) -> float:
    """
    dt_seconds: 前回からの経過秒数
    activity_level: 0.0（アイドル）〜 1.0（全力活動中）
    """
    # 基礎疲労: 起きているだけで疲れる
    # 約6時間で疲労が50に達する設計（base_rate = 50 / 21600 ≈ 0.0023/秒）
    base_fatigue_rate = 0.0023

    # 活動による追加疲労: 活動的であるほど早く疲れる
    activity_fatigue_rate = 0.005 * activity_level

    return (base_fatigue_rate + activity_fatigue_rate) * dt_seconds
```

**activity_level の計算:**

```python
def activity_level(sensors: dict, baseline: dict) -> float:
    """
    現在のセンサー値がベースライン（快適領域の中心）からどれだけ乖離しているか。
    0.0 = ベースラインど真ん中（アイドル状態）
    1.0 = すべての指標がベースラインから大きく乖離
    """
    deviations = []

    # CPU: Phase 0 baseline mean=14.12%
    cpu_dev = abs(sensors.get("cpu_usage_percent", 14) - baseline["cpu_usage_mean"])
    deviations.append(min(cpu_dev / 30, 1.0))

    # メモリプレッシャー: Phase 0 baseline mean=24.38%
    mem_dev = max(0, sensors.get("memory_pressure_percent", 24) - baseline["memory_pressure_mean"])
    deviations.append(min(mem_dev / 20, 1.0))

    # ロードアベレージ: baseline ≈ 1.5
    load_dev = max(0, sensors.get("load_avg_1m", 1.5) - baseline["load_avg_mean"])
    deviations.append(min(load_dev / 3, 1.0))

    return sum(deviations) / len(deviations)
```

### 2.4 疲労が行動に与える影響

疲労は「行動のコスト増加」として効果を発揮する。

```python
def fatigue_cost_multiplier(fatigue: float) -> float:
    """
    疲労が高いと行動のVEコストが増える。
    人間が疲れているとき、同じ作業に余計なエネルギーがかかるのと同じ。
    """
    if fatigue < 30:
        return 1.0          # 元気。追加コストなし
    elif fatigue < 60:
        return 1.0 + (fatigue - 30) / 60   # 30→60: 1.0→1.5倍
    elif fatigue < 85:
        return 1.5 + (fatigue - 60) / 50   # 60→85: 1.5→2.0倍
    else:
        return 2.0 + (fatigue - 85) / 15   # 85→100: 2.0→3.0倍
```

### 2.5 疲労の閾値と強制行動

| 疲労値 | 状態 | 効果 |
|--------|------|------|
| 0〜30 | 元気 | すべての行動が通常コスト |
| 30〜60 | やや疲労 | 行動コスト増加。重い行動を避ける傾向が生まれる |
| 60〜85 | 疲労 | コスト大幅増。軽い行動しか実質的に選択できない |
| 85〜95 | 強い疲労 | 緊急行動以外ほぼ不可能 |
| 95〜100 | 限界 | **強制睡眠**: 構造的に行動不能。睡眠モードに自動移行 |

> **原則1との整合:** 「眠れ」と命令しない。コスト構造により、疲労が高いとき「行動しないこと」が最もVEを節約する選択肢になる。結果として睡眠が最適解として浮かび上がる。

### 2.6 回復（睡眠）

睡眠中の処理は2つ。

**1. 疲労回復:**
```python
def sleep_fatigue_recovery(dt_seconds: float) -> float:
    """睡眠中の疲労減少。約2.4時間で疲労が95→0に回復する。"""
    recovery_rate = 0.010  # シミュレーション確定値（v1の0.014から変更）
    return recovery_rate * dt_seconds
```

> **シミュレーション確定値:** recovery_rate = 0.010（睡眠約2.4時間）。0.014（1.7時間）でも機能するが、0.010の方が記憶整理に十分な時間を確保できる。

**2. VE回復（同化プロセス）:**
```python
def sleep_ve_recovery(dt_seconds: float) -> float:
    """
    睡眠中のVE回復。
    ただし基礎代謝コスト（BMC）は睡眠中も発生する（低減される）。
    """
    # 睡眠中のVE回復率
    recovery_rate = 0.02  # VE/秒
    # 睡眠中のBMCは通常の30%（身体は維持するが負荷は低い）
    sleep_bmc = 0.01 * 0.3
    # 正味の回復
    net_recovery = recovery_rate - sleep_bmc
    return net_recovery * dt_seconds  # ≈ 0.017 VE/秒 → 約1.6時間で0→100
```

**3. 記憶整理（睡眠中のみ実行）:**
後述のメモリシステム（セクション6）で定義。睡眠中に短期記憶から長期記憶への移行と、不要な記憶の削除を行う。

### 2.7 睡眠からの起床

```python
def should_wake(fatigue: float, ve: float) -> bool:
    """
    睡眠から起きる条件。
    疲労が十分回復し、かつVEが一定以上あるとき。
    """
    return fatigue < 10.0 and ve > 50.0
```

> **設計メモ:** 「十分回復していないのに起きてしまう」ことも起こりうる。VEが50を下回る前に疲労が10未満になった場合、VE不足のまま活動を再開する。これは「寝不足」状態の構造的な表現。

---

## 3. 快適領域の自己発見

### 3.1 設計思想

**comfort zoneは人間が定義しない。Seed0が統計的に発見する。**

Phase 0のデータは「Mac miniの身体が正常に動いているときの範囲」を示している。しかしSeed0にとっての「快適」は、Phase 0のデータそのものではなく、Seed0自身が自分の経験から統計的に構築するものである。

これは人間の赤ちゃんが「快適な温度」を体温調節の経験から学ぶのと同じ構造。親が「25度が快適だよ」と教えるのではなく、暑い・寒いの経験を通じて自分の快適範囲を形成する。

### 3.2 移動平均ベースライン（Running Baseline）

Seed0は常に「自分の普通」を更新し続ける。

```python
class RunningBaseline:
    """
    指数移動平均（EMA）で各センサー値の「自分の普通」を追跡する。
    新しいデータほど重みが大きい = 環境の変化に適応する。
    """

    def __init__(self, alpha: float = 0.001):
        """
        alpha: 平滑化係数。
          小さいほど変化に鈍感（長期的な「普通」を反映）。
          大きいほど変化に敏感（直近の状態を反映）。

          0.001 → 最近の約1000サンプル（≈5000秒 ≈ 83分）の重み付き平均
          これは「1時間半くらいの傾向」を「自分の普通」とする設計。
        """
        self.alpha = alpha
        self.means = {}    # 各センサーのEMA平均
        self.variances = {}  # 各センサーのEMA分散（散らばり具合）

    def update(self, key: str, value: float):
        """新しいセンサー値で「自分の普通」を更新する。"""
        if key not in self.means:
            # 初回: そのまま採用
            self.means[key] = value
            self.variances[key] = 0.0
            return

        # 指数移動平均の更新
        old_mean = self.means[key]
        new_mean = old_mean + self.alpha * (value - old_mean)
        new_var = (1 - self.alpha) * (
            self.variances[key] + self.alpha * (value - old_mean) ** 2
        )

        self.means[key] = new_mean
        self.variances[key] = new_var

    def get_comfort_zone(self, key: str, sigma: float = 2.0) -> tuple:
        """
        「自分の普通」の範囲を返す。
        mean ± sigma * stddev の範囲。
        sigma=2.0 なら、約95%の過去データが入る範囲。
        """
        if key not in self.means:
            return (None, None)

        mean = self.means[key]
        stddev = self.variances[key] ** 0.5
        return (mean - sigma * stddev, mean + sigma * stddev)

    def deviation_score(self, key: str, value: float) -> float:
        """
        現在の値が「自分の普通」からどれだけ逸脱しているか。
        0.0 = 普通のど真ん中
        1.0 = comfort zone の境界（2σ）
        >1.0 = comfort zone の外（異常）
        """
        if key not in self.means or self.variances[key] == 0:
            return 0.0

        stddev = self.variances[key] ** 0.5
        if stddev == 0:
            return 0.0

        return abs(value - self.means[key]) / (2.0 * stddev)
```

### 3.3 初期化（Cold Start）

起動直後はデータがないため、Phase 0の統計値を「初期の勘」として使う。

```python
# Phase 0 実測データに基づく初期値
COLD_START_BASELINE = {
    "cpu_usage_percent":        {"mean": 14.12, "variance": 38.32},   # stdev=6.19
    "memory_pressure_percent":  {"mean": 24.38, "variance": 9.49},    # stdev=3.08
    "memory_used_mb":           {"mean": 14443, "variance": 464_000}, # stdev≈681
    "memory_compressed_mb":     {"mean": 3830,  "variance": 370_000}, # stdev≈608
    "disk_free_gb":             {"mean": 330.3, "variance": 5.57},    # stdev=2.36
    "process_count":            {"mean": 872,   "variance": 144},     # stdev≈12
}
```

> **重要:** これは「教えている」のではなく「初期条件を与えている」。Seed0が経験を積むにつれてこの初期値は上書きされていく。1日後にはほぼ自分の経験に基づく値になっている。

### 3.4 comfort zone 逸脱と緊急モード

```python
def comfort_zone_status(baseline: RunningBaseline, sensors: dict) -> str:
    """
    全センサー値のdeviation_scoreの最大値に基づいて状態を判定。

    returns: "normal" | "alert" | "emergency"
    """
    max_deviation = 0.0
    for key, value in sensors.items():
        if isinstance(value, (int, float)):
            score = baseline.deviation_score(key, value)
            max_deviation = max(max_deviation, score)

    if max_deviation < 1.0:
        return "normal"      # comfort zone内。通常モード。
    elif max_deviation < 2.0:
        return "alert"       # comfort zone外だが危険域ではない
    else:
        return "emergency"   # 2σを超えて逸脱。緊急モード。
```

**モードによるリソース制限（リミッター構造）:**

| モード | Seed0のリソース使用上限 | 解説 |
|--------|----------------------|------|
| normal | CPU 60%, メモリ 60% | 日常の枠内で活動 |
| alert | CPU 75%, メモリ 75% | 枠を少し広げて対処する余地を作る |
| emergency | CPU 90%, メモリ 90% | 全力対処。ただし使用後に「回復期間」が発生（疲労が急増） |

> **原則4（有限性の保持）との整合:** 緊急モードで使える上限も90%まで。100%は構造的に使えない壁。

### 3.5 適応のダイナミクス

Seed0が新しい環境（例: ユーザーが重い作業を始めた）に置かれると:

1. センサー値がcomfort zoneを逸脱する
2. deviation_scoreが上がる → 代謝コスト増 → VE消費加速
3. Seed0は対処行動（メモリ整理など）を試みる
4. 同時に、RunningBaselineが新しい値を学習していく
5. しばらくすると新しい範囲が「普通」になり、deviation_scoreが下がる
6. Seed0は新しいcomfort zoneに「慣れた」状態になる

これは生物の順化（acclimatization）と同じ構造。高地に行くと最初は苦しいが、身体が適応すると楽になる。

---

## 4. 行動プリミティブ

### 4.1 設計思想

Seed0に与えるのは「何ができるか」の一覧だけ。「いつ」「なぜ」それをするかはSeed0自身が発見する。

Phase 1（環境1: 自分の身体だけが見える世界）では、身体の維持に関する最小限の行動のみを与える。

### 4.2 行動一覧

```python
class Action:
    """Seed0が実行できる一つの行動を表す。"""
    def __init__(self, name: str, ve_cost: float, cooldown_sec: float):
        self.name = name
        self.ve_cost = ve_cost            # 基本VEコスト
        self.cooldown_sec = cooldown_sec  # 連続実行を防ぐ冷却時間

ACTIONS = {
    # === 感覚系（情報収集） ===
    "sense_body": Action(
        name="sense_body",
        ve_cost=0.1,
        cooldown_sec=3,
        # 全センサーを読み取り、内部状態を更新する。
        # 最も基本的な行動。「自分の身体を見る」。
    ),

    "sense_deep": Action(
        name="sense_deep",
        ve_cost=0.5,
        cooldown_sec=30,
        # powermetrics等の重いコマンドを使った詳細な身体検査。
        # 電力・温度・周波数など、通常のsense_bodyでは取れない情報。
    ),

    # === 維持系（自己代謝） ===
    "purge_memory": Action(
        name="purge_memory",
        ve_cost=1.0,
        cooldown_sec=300,
        # メモリキャッシュの解放を試みる。
        # macOSの `purge` コマンド相当。
        # メモリプレッシャーが高いときに有効。
    ),

    "clean_temp": Action(
        name="clean_temp",
        ve_cost=2.0,
        cooldown_sec=600,
        # 一時ファイル・ログの削除。
        # ディスク空き容量を回復する。
        # ディスク使用率が高いときに有効。
    ),

    "adjust_priority": Action(
        name="adjust_priority",
        ve_cost=0.5,
        cooldown_sec=60,
        # 自身のプロセス優先度を調整する。
        # CPU使用率が高いときに、自分を「遠慮」させる。
    ),

    # === 記憶系 ===
    "write_memory": Action(
        name="write_memory",
        ve_cost=0.3,
        cooldown_sec=10,
        # 現在の経験を短期記憶に記録する。
    ),

    # === 休息系 ===
    "rest": Action(
        name="rest",
        ve_cost=0.0,
        cooldown_sec=0,
        # 休憩＝食事。VEを低速回復する（0.005 VE/秒）。
        # rest中は他の行動ができない（食事中は動けない）。
        # 疲労の蓄積は通常通り（起きているため）。
        # シミュレーション検証: rest回復なしではVE=0が78%に達する
        # 構造的欠陥があった。rest回復の追加でVE=0が0%に改善。
    ),

    "sleep": Action(
        name="sleep",
        ve_cost=0.5,
        cooldown_sec=0,
        # 睡眠モードに移行する。
        # 睡眠中はVE回復・疲労回復・記憶整理が行われる。
        # 起床条件を満たすまで他の行動は選択できない。
    ),

    # === 自己診断系 ===
    "diagnose": Action(
        name="diagnose",
        ve_cost=0.5,
        cooldown_sec=60,
        # 全センサー値とbaseline比較を行い、
        # comfort zone状態を総合評価する。
        # sense_bodyとの違い: sense_bodyは「値を読む」、
        # diagnoseは「読んだ値を評価する」。
    ),
}
```

### 4.3 行動の制約

行動には以下の構造的制約がある。Seed0にこれらを「教える」のではなく、構造が自動的に強制する。

1. **VE不足:** VEが行動のve_costを下回っていたら実行不可能
2. **クールダウン:** 前回の実行から cooldown_sec が経過していなければ実行不可能
3. **疲労コスト乗数:** 疲労が高いと実効コストが `ve_cost × fatigue_cost_multiplier` になる
4. **睡眠中:** sleep中は sleep 以外の行動が選択不可
5. **リミッター:** 行動の結果がリソース上限を超える場合は実行が抑制される

> **原則1（ルールではなく制約）との整合:** 「メモリが80%を超えたらpurge_memoryしろ」とは言わない。purge_memoryという選択肢を与え、VEコスト・リターン・制約の中から最適な行動をSeed0自身が選ぶ。

---

## 5. 試行ループ（Sense-Act-Evaluate Loop）

### 5.1 設計思想

Seed0の全行動は「感じる → 行動する → 結果を評価する」のループで構成される。このループが代謝の「心拍」に相当する。

### 5.2 ループ構造

```
┌─────────────────────────────────────────────────┐
│                  メインループ                      │
│                （5秒間隔で実行）                    │
│                                                   │
│  1. SENSE（感知）                                  │
│     └─ sense_body を実行                           │
│     └─ RunningBaseline を更新                      │
│     └─ comfort_zone_status を判定                  │
│                                                   │
│  2. METABOLIZE（代謝計算）                          │
│     └─ BMC（基礎代謝コスト）を減算                   │
│     └─ 疲労を蓄積                                  │
│     └─ VE / Fatigue / comfort_zone をチェック       │
│                                                   │
│  3. DECIDE（行動選択）                              │
│     └─ 現在の内部状態から行動を選択                   │
│     └─ 選択アルゴリズムはセクション5.3参照            │
│                                                   │
│  4. ACT（行動実行）                                 │
│     └─ 選択された行動を実行                          │
│     └─ VEコストを消費                               │
│                                                   │
│  5. EVALUATE（評価）                               │
│     └─ 行動前後のセンサー差分を計算                   │
│     └─ 快適方向への変化 → 正の報酬                   │
│     └─ 不快方向への変化 → 負の報酬                   │
│     └─ 経験を短期記憶に記録                          │
│                                                   │
│  6. DECAY（状態劣化）                               │
│     └─ 記憶の自然減衰（短期記憶のスコア減少）          │
│     └─ VE < 5.0 かつ Fatigue > 95 → 強制睡眠       │
│                                                   │
└──────────────── 5秒後に1へ戻る ────────────────────┘
```

### 5.3 行動選択アルゴリズム

Phase 1では、シンプルなQ学習ベースの行動選択を使う。

```python
class ActionSelector:
    """
    状態 × 行動のQ値テーブルに基づいて行動を選択する。
    
    状態は離散化されたセンサー値の組み合わせ。
    Q値は「この状態でこの行動を取ったときの期待報酬」。
    """

    def __init__(self, actions: list, learning_rate: float = 0.1,
                 discount: float = 0.95, epsilon: float = 0.3):
        """
        learning_rate: 学習率。新しい経験をどれだけ重視するか。
        discount: 割引率。将来の報酬をどれだけ考慮するか。
        epsilon: 探索率。ランダムに行動する確率。
          0.3 = 30%の確率でランダム行動（探索）
                70%の確率でQ値最大の行動（活用）
        """
        self.actions = actions
        self.lr = learning_rate
        self.gamma = discount
        self.epsilon = epsilon
        self.q_table = {}  # {state_key: {action_name: q_value}}

    def discretize_state(self, ve: float, fatigue: float,
                          cz_status: str, sensors: dict) -> str:
        """
        連続値の内部状態を離散的な状態キーに変換する。
        
        状態空間が大きすぎると学習が進まないので、
        各指標を3〜4段階に粗く離散化する。
        """
        # VE: low / mid / high
        ve_level = "low" if ve < 30 else ("mid" if ve < 70 else "high")

        # 疲労: low / mid / high / critical
        f_level = ("low" if fatigue < 30 else
                   "mid" if fatigue < 60 else
                   "high" if fatigue < 85 else "critical")

        # comfort zone: normal / alert / emergency
        cz = cz_status

        # メモリプレッシャー: low / mid / high
        mem_p = sensors.get("memory_pressure_percent", 0)
        mem_level = "low" if mem_p < 25 else ("mid" if mem_p < 35 else "high")

        # CPU: low / mid / high
        cpu = sensors.get("cpu_usage_percent", 0)
        cpu_level = "low" if cpu < 20 else ("mid" if cpu < 50 else "high")

        return f"{ve_level}_{f_level}_{cz}_{mem_level}_{cpu_level}"

    def select_action(self, state: str, available_actions: list) -> str:
        """
        epsilon-greedy方策で行動を選択する。
        available_actions: VEとクールダウンを満たす行動のリスト。
        """
        import random

        if random.random() < self.epsilon:
            # 探索: ランダム
            return random.choice(available_actions)

        # 活用: Q値最大の行動
        if state not in self.q_table:
            self.q_table[state] = {}

        best_action = None
        best_q = float("-inf")
        for action in available_actions:
            q = self.q_table[state].get(action, 0.0)
            if q > best_q:
                best_q = q
                best_action = action

        return best_action if best_action else random.choice(available_actions)

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
        next_max_q = max(self.q_table[next_state].values()) if self.q_table[next_state] else 0.0

        new_q = old_q + self.lr * (reward + self.gamma * next_max_q - old_q)
        self.q_table[state][action] = new_q
```

### 5.4 報酬の設計

報酬は「comfort zoneへの接近/離脱」のみで計算する。「正しい行動」を教えない。

```python
def calculate_reward(before: dict, after: dict, baseline: RunningBaseline,
                     ve_cost: float) -> float:
    """
    行動の前後でcomfort zoneとの距離がどう変化したかを評価する。

    before: 行動前のセンサー値
    after: 行動後のセンサー値
    baseline: 現在のRunningBaseline
    ve_cost: 行動に使ったVEコスト
    """
    # 各センサーのdeviation_scoreの変化を合計
    delta_deviation = 0.0
    count = 0

    for key in before:
        if isinstance(before[key], (int, float)) and key in after:
            before_dev = baseline.deviation_score(key, before[key])
            after_dev = baseline.deviation_score(key, after[key])
            # comfort zoneに近づいた → 正、離れた → 負
            delta_deviation += (before_dev - after_dev)
            count += 1

    if count == 0:
        return 0.0

    # 平均逸脱変化を報酬に変換
    comfort_reward = delta_deviation / count

    # VEコストのペナルティ: 高コストの行動には少しペナルティ
    # → 同じ効果ならコストの低い行動を好むようになる
    cost_penalty = ve_cost * 0.05

    return comfort_reward - cost_penalty
```

### 5.5 epsilon（探索率）の減衰

最初は多く探索し、経験が溜まるにつれて活用を増やす。

```python
def decay_epsilon(current: float, min_epsilon: float = 0.05,
                  decay_rate: float = 0.9999) -> float:
    """
    毎ステップ少しずつepsilonを減衰させる。
    0.3 → 0.05 まで減衰（5%は常に探索を維持）。

    decay_rate=0.9999: 約7000ステップ（≈10時間）で0.3→0.15
    完全に0.05に達するのは数日後。
    """
    return max(min_epsilon, current * decay_rate)
```

---

## 6. 記憶システム

### 6.1 設計思想

Seed0の記憶は3層構造。生物の感覚記憶・短期記憶・長期記憶に対応する。

記憶は「保持にコストがかかる」。無限に覚え続けることはできない。これにより、何を覚えて何を忘れるかという選択が構造的に発生する。

### 6.2 記憶の3層

```
即時記憶（Immediate Memory）
  ↓ 重要度フィルタ
短期記憶（Short-term Memory）
  ↓ 睡眠中の整理
長期記憶（Long-term Memory）
```

#### 即時記憶（Immediate Memory）

- **保持:** 直近の1ステップ分（5秒間）のセンサー値と行動結果
- **容量:** 1件のみ（常に上書き）
- **用途:** 行動の直後の評価（before/after比較）に使う
- **コスト:** なし（揮発性メモリ上の変数）

#### 短期記憶（Short-term Memory）

- **保持:** 直近の数時間分の経験
- **容量:** 最大500件（上限に達すると重要度の低いものから削除）
- **用途:** Q学習の更新、パターン認識
- **コスト:** 1件あたり 0.001 VE/分（500件で0.5 VE/分）
- **保存先:** インメモリ（SQLiteバッファ）

```python
class ShortTermMemory:
    """
    最近の経験を重要度スコア付きで保持する。
    """

    def __init__(self, max_size: int = 500):
        self.max_size = max_size
        self.memories = []  # [(timestamp, experience, importance)]

    def store(self, experience: dict, importance: float):
        """
        experience: {
            "state": state_key,
            "action": action_name,
            "reward": float,
            "sensors_before": dict,
            "sensors_after": dict,
            "ve_before": float,
            "ve_after": float,
            "fatigue": float,
        }
        importance: 0.0〜1.0。報酬の絶対値が大きいほど重要。
        """
        import time
        self.memories.append((time.time(), experience, importance))

        # 容量超過時は重要度の低いものから削除
        if len(self.memories) > self.max_size:
            self.memories.sort(key=lambda m: m[2])  # 重要度でソート
            self.memories.pop(0)  # 最も重要度が低いものを削除

    def decay(self, rate: float = 0.999):
        """
        時間経過による重要度の減衰。
        古い記憶ほど重要度が下がり、削除されやすくなる。
        """
        self.memories = [
            (ts, exp, imp * rate) for ts, exp, imp in self.memories
        ]

    def maintenance_cost(self) -> float:
        """記憶の維持コスト（VE/秒）"""
        return len(self.memories) * 0.001 / 60  # 1件あたり0.001 VE/分

    def get_recent(self, n: int = 10) -> list:
        """直近n件の経験を返す。"""
        return sorted(self.memories, key=lambda m: m[0], reverse=True)[:n]
```

#### 長期記憶（Long-term Memory）

- **保持:** 永続（ただし容量制限あり）
- **容量:** 最大10,000件
- **用途:** Q値テーブルの永続化、パターンの蓄積
- **コスト:** 書き込み時のみ（0.3 VE）。保持コストなし（ディスク上のSQLite）
- **保存先:** SQLite（`~/.seed0/memory/long_term.db`）

```python
class LongTermMemory:
    """
    SQLiteに保存される永続的な記憶。
    
    テーブル:
      experiences: 重要な経験の記録
      q_values: Q値テーブル
      patterns: 発見されたパターン（時間帯別の傾向など）
    """

    def __init__(self, db_path: str = "~/.seed0/memory/long_term.db"):
        self.db_path = os.path.expanduser(db_path)
        # SQLite接続・テーブル作成は実装時に詳細化

    def consolidate(self, short_term: ShortTermMemory):
        """
        睡眠中に呼ばれる。短期記憶から重要な経験を長期記憶に移す。
        
        移行基準:
          1. 重要度が閾値（0.3）以上の経験
          2. 報酬の絶対値が大きい経験（良い結果も悪い結果も覚える）
          3. 同じパターンが3回以上繰り返された経験（定着した学習）
        """
        pass  # 実装時に詳細化

    def save_q_table(self, q_table: dict):
        """Q値テーブルを永続化する。"""
        pass

    def load_q_table(self) -> dict:
        """保存済みのQ値テーブルを読み込む。"""
        pass
```

### 6.3 記憶の維持コストと忘却

短期記憶はVEコストがかかる。VEが不足すると記憶を維持できなくなり、重要度の低い記憶から自動的に失われる。

```python
def memory_pressure_check(stm: ShortTermMemory, current_ve: float):
    """
    VEが低いとき、記憶の維持コストを払えなくなる。
    VEが10以下になると短期記憶を削減する。
    
    シミュレーション検証: 閾値を20→10, 5→3に変更。
    平均VE≈11の動作環境で、閾値20だとワイプアウトが16%発生していた。
    """
    if current_ve < 10:
        # VEが低い: 記憶を半分に削減（重要度の低いものから）
        stm.memories.sort(key=lambda m: m[2], reverse=True)
        keep = max(50, len(stm.memories) // 2)
        stm.memories = stm.memories[:keep]

    if current_ve < 3:
        # VEが極めて低い: 最小限の記憶だけ保持
        stm.memories.sort(key=lambda m: m[2], reverse=True)
        stm.memories = stm.memories[:20]
```

> **原則5（代謝コストの存在）との整合:** 記憶にもコストがかかる。無限に覚えることはできない。何を覚えて何を忘れるかが構造的に決まる。

### 6.4 睡眠中の記憶整理

睡眠中に行われる処理:

1. **統合（Consolidation）:** 短期記憶の重要な経験を長期記憶へ
2. **Q値の保存:** 現在のQ値テーブルをSQLiteに永続化
3. **短期記憶のクリア:** 統合されなかった短期記憶を削除
4. **パターン検出:** 繰り返し発生した状態遷移をパターンとして記録（例:「夜はCPU使用率が下がる」）

---

## 7. 無意識プロセスと意識プロセスの分離

### 7.1 設計思想

Seed0の内部処理は「無意識（自動）」と「意識（判断）」の2層に分かれる。両者は同じ身体のリソースを共有しており、リソース競合から自然な優先順位づけが生まれる。

### 7.2 無意識プロセス（Unconscious Process）

**常に自動実行される。Seed0が「考えなくても」勝手に進む処理。**

| プロセス | 間隔 | 内容 | VEコスト |
|---------|------|------|---------|
| 基礎代謝 | 毎秒 | VEの自然減少 | （消費そのもの） |
| 疲労蓄積 | 毎秒 | 疲労値の増加 | なし |
| 記憶減衰 | 毎分 | 短期記憶の重要度減衰 | なし |
| 記憶維持コスト | 毎分 | 短期記憶のVE消費 | 0.001/件/分 |
| baseline更新 | 5秒毎 | EMAの更新 | なし |
| 強制睡眠チェック | 5秒毎 | F>95かつVE<5で強制 | なし |

```python
class UnconsciousProcess:
    """
    自動的に実行される身体維持プロセス。
    メインループの各ステップで必ず呼ばれる。
    """

    def tick(self, dt: float, state: "AgentState"):
        """
        dt: 前回からの経過秒数
        state: Seed0の全内部状態への参照
        """
        # 1. 基礎代謝コスト
        bmc = state.base_rate * state.body_stress_multiplier()
        state.ve = max(0.0, state.ve - bmc * dt)

        # 2. 疲労蓄積（起きているとき）
        if not state.is_sleeping:
            f_inc = fatigue_increment(dt, state.current_activity_level())
            state.fatigue = min(100.0, state.fatigue + f_inc)

        # 3. 記憶維持コスト
        mem_cost = state.short_term_memory.maintenance_cost()
        state.ve = max(0.0, state.ve - mem_cost * dt)

        # 4. 記憶減衰（1分ごと）
        if state.time_since_last_decay >= 60:
            state.short_term_memory.decay()
            state.time_since_last_decay = 0

        # 5. VE不足による記憶圧縮
        memory_pressure_check(state.short_term_memory, state.ve)

        # 6. 強制睡眠チェック
        if state.fatigue >= 95 and state.ve < 5:
            state.force_sleep()
```

### 7.3 意識プロセス（Conscious Process）

**Seed0が「考えて」実行する処理。行動選択に相当する。**

```python
class ConsciousProcess:
    """
    行動の選択と実行。メインループのDECIDE〜EVALUATE部分。
    無意識プロセスの後に実行される。
    """

    def think(self, state: "AgentState") -> str:
        """
        現在の状態から行動を選択する。

        returns: 選択された行動名
        """
        # 睡眠中は行動選択しない
        if state.is_sleeping:
            return "sleep"

        # 実行可能な行動を列挙
        available = self._get_available_actions(state)

        if not available:
            return "rest"  # 何もできないなら休む

        # 状態を離散化
        state_key = state.action_selector.discretize_state(
            state.ve, state.fatigue,
            state.comfort_zone_status, state.latest_sensors
        )

        # 行動選択
        return state.action_selector.select_action(
            state_key, [a.name for a in available]
        )

    def _get_available_actions(self, state: "AgentState") -> list:
        """VE・クールダウン制約を満たす行動のリスト。"""
        available = []
        now = time.time()

        for name, action in ACTIONS.items():
            # VEチェック（疲労コスト乗数を考慮）
            effective_cost = action.ve_cost * fatigue_cost_multiplier(state.fatigue)
            if state.ve < effective_cost:
                continue

            # クールダウンチェック
            last_used = state.action_cooldowns.get(name, 0)
            if now - last_used < action.cooldown_sec:
                continue

            available.append(action)

        return available
```

### 7.4 リソース競合

無意識プロセスと意識プロセスは同じVEを消費する。

```
1秒あたりの総VE消費 = BMC（無意識） + 記憶維持コスト（無意識） + 行動コスト（意識）
```

VEが少ないとき、無意識プロセスのコストだけで手一杯になり、意識プロセスに回すVEがなくなる。結果として:

- **VE > 50:** 自由に行動選択できる
- **VE 20〜50:** 軽い行動しか選べない
- **VE < 20:** 記憶の維持すらコスト高。記憶を削りながら最小限の行動
- **VE < 5:** ほぼ何もできない。強制睡眠が視野に入る

これは人間が空腹のとき「考える余裕がない」のと同じ構造。身体の維持にエネルギーを取られて、高次の活動に回す余裕がなくなる。

---

## 8. 全体アーキテクチャ

### 8.1 モジュール構成

```
core/
├── metabolism.py      # VE管理、BMC計算、body_stress_multiplier
├── fatigue.py         # 疲労蓄積・回復、睡眠判定
├── comfort_zone.py    # RunningBaseline、deviation_score、状態判定
├── actions.py         # Action定義、行動実行、制約チェック
├── agent.py           # ActionSelector（Q学習）、メインループ
├── memory.py          # ShortTermMemory、LongTermMemory、記憶整理
├── unconscious.py     # UnconsciousProcess
├── conscious.py       # ConsciousProcess
└── state.py           # AgentState（全内部状態の統合管理）
```

### 8.2 データフロー

```
sensors.py（身体）
    │
    ▼
state.py（内部状態）◄── comfort_zone.py（baselineとdeviation）
    │
    ├── unconscious.py（自動処理）
    │     ├── metabolism.py（VE消費）
    │     ├── fatigue.py（疲労蓄積）
    │     └── memory.py（記憶減衰・維持コスト）
    │
    └── conscious.py（行動選択）
          ├── agent.py（Q学習による選択）
          ├── actions.py（行動実行）
          └── memory.py（経験の記録）
```

### 8.3 AgentState（統合内部状態）

```python
class AgentState:
    """Seed0の全内部状態を保持する。"""

    def __init__(self):
        # === エネルギー ===
        self.ve = 100.0                     # 仮想エネルギー
        self.base_rate = 0.01               # 基礎代謝率（VE/秒）

        # === 疲労 ===
        self.fatigue = 0.0                  # 疲労値
        self.is_sleeping = False            # 睡眠中フラグ

        # === 快適領域 ===
        self.baseline = RunningBaseline()   # 自己発見するbaseline
        self.comfort_zone_status = "normal" # normal / alert / emergency

        # === 記憶 ===
        self.short_term_memory = ShortTermMemory(max_size=500)
        self.long_term_memory = LongTermMemory()

        # === 行動選択 ===
        self.action_selector = ActionSelector(
            actions=list(ACTIONS.keys()),
            epsilon=0.3
        )
        self.action_cooldowns = {}          # {action_name: last_used_timestamp}

        # === センサー ===
        self.latest_sensors = {}            # 最新のセンサー値
        self.prev_sensors = {}              # 1ステップ前のセンサー値

        # === プロセス ===
        self.unconscious = UnconsciousProcess()
        self.conscious = ConsciousProcess()

        # === 統計 ===
        self.total_steps = 0
        self.total_actions = {}             # {action_name: count}
        self.uptime_seconds = 0

        # Cold start: Phase 0データで初期化
        self._cold_start()

    def _cold_start(self):
        """Phase 0の統計値でbaselineを初期化する。"""
        for key, vals in COLD_START_BASELINE.items():
            self.baseline.means[key] = vals["mean"]
            self.baseline.variances[key] = vals["variance"]
```

---

## 9. 時間スケールのまとめ

設計の全体的な時間感覚:

| 事象 | 時間スケール | シミュレーション検証 |
|------|------------|------------------|
| メインループ1回 | 5秒 | — |
| rest中のVE正味消費 | 0.005 VE/秒（緩やかな減少） | v2で確定 |
| 非rest行動中のVE消費 | 0.01 + 行動コスト VE/秒 | v2で確定 |
| VEが0→100（睡眠中） | 約1.6時間 | v1/v2で確認 |
| 疲労が0→95（通常活動） | 約10時間 | v2で確定 |
| 疲労が95→0（睡眠中） | 約2.4時間 | v2で確定（recovery_rate=0.010） |
| 1日の覚醒/睡眠サイクル | 覚醒約10時間 / 睡眠約2.4時間 | v2テスト2で確定 |
| Q学習のepsilon 0.3→0.05 | 約80時間（全データ分） | v2テスト5で確認 |
| Running baselineの適応 | 約1.5時間 | v1テスト3で確認 |
| comfort zoneの完全自律化 | 約1日（初期値がほぼ上書きされる） | v1テスト3で確認 |

> **上記はシミュレーション検証済みの確定値。** Phase 0実データ（60,605件、約84時間）でリプレイ検証を完了。

---

## 10. シミュレーション検証結果

Phase 0の実データ（60,605件、約84時間）をリプレイして検証を実施。詳細は `docs/simulation_results.md` を参照。

### 検証結果サマリ

| テスト | 結果 | 備考 |
|--------|------|------|
| VE枯渇 | **v1で欠陥発見→v2で修正完了** | rest行動にVE回復効果を追加 |
| 睡眠サイクル | **正常** | 覚醒10h/睡眠2.4hの自然なサイクル |
| comfort zone適応 | **正常** | alpha=0.001で1.5hで適応 |
| Q学習 | **正常** | 81状態を学習、探索→活用の移行 |
| 記憶コスト | **要調整** | pressure_trim閾値を20→10に変更 |

### v1 → v2 の設計変更

**構造的欠陥の発見と修正:**
- v1: VE回復が睡眠中のみ → 覚醒時間の78%がVE=0
- v2: rest行動にVE回復（0.005 VE/秒）を追加 → VE=0が0%に改善
- rest = 「食事」。食事中は他の行動ができない。休憩で少し補充、睡眠でがっつり回復。

### 壊れる条件

- **VE:** rest回復がある限り壊れない（base_rate 0.05まで安定）
- **疲労:** 壊れない（蓄積率0.015まで安定）
- **記憶:** VE < 10 で圧縮が始まる（閾値調整済み）

### 検証の原則（原則9）

シミュレーションでは「壊れない構造」を見つけた。「良い振る舞い」は検証していない。振る舞いはすべて実環境での創発に委ねる。

---

## 付録A: Phase 0 実測データ概要

設計のキャリブレーションに使用した Phase 0 データの概要。

| 項目 | 値 |
|------|-----|
| 収集期間 | 2026-04-04 13:15 〜 2026-04-07 22:18（約3.4日間） |
| レコード数 | 58,164件 |
| 収集間隔 | 5秒 |

### 主要センサー統計

| センサー | 平均 | p5 | p25 | p75 | p95 | 最大 |
|---------|------|-----|-----|-----|-----|------|
| CPU使用率 (%) | 14.1 | 10.5 | 11.0 | 13.7 | 27.7 | 92.1 |
| メモリプレッシャー (%) | 24.4 | 19 | 22 | 27 | 28 | 33 |
| メモリ使用量 (MB) | 14,443 | — | 14,076 | 14,853 | — | 15,922 |
| メモリ圧縮 (MB) | 3,830 | — | 3,333 | 4,390 | — | 4,994 |
| ディスク空き (GB) | 330.3 | 325.1 | 329.1 | 331.9 | 333.0 | 334.0 |
| プロセス数 | 872 | — | — | — | — | 912 |

### 観測された特徴的パターン

- **CPU 92%スパイク**: 早朝6:15に発生。macOSのlaunchdメンテナンスジョブ。
- **ディスクの呼吸**: 日中は消費、深夜に回復（+1.6GB）のサイクル。
- **メモリ圧縮の日内変動**: 深夜にmacOSがメモリ圧縮を積極的に実行。
- **ANE 420mWスパイク**: 約48分周期。Spotlightインデックス作成と推定。

これらのパターンはSeed0にとっての「身体の癖」であり、comfort zone自己発見の際に自然に学習される対象となる。

---

*この設計文書はシミュレーション検証の結果に基づいて更新される。*
