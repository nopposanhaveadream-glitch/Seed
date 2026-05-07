# Seed0 Current State

> 最終更新: 2026-05-06 11:35 JST
> 目的: 圧縮後・新セッション開始時に、長い履歴を読む前に現在地へ戻るための短いコンパス。

## 1. 現在地

Seed0 は Phase 1 フェーズCを 2026-05-01 13:55:45 に graceful shutdown で終了済み。

2026-05-06 時点では、AOR（観察層、Action Outcome Recorder）統合済みの `core/agent.py` で実機再起動済み。現在は環境2へ直進するフェーズDではなく、環境1.5「観察と予測の身体化」として扱う。

中心問い:

> 遊ばせる前に、遊びから学べる身体がいる。

## 2. 実機状態（2026-05-06 11:35 JST）

`~/.seed0/status.json` より:

| 項目 | 値 |
|---|---:|
| status timestamp | 2026-05-06 11:35:11 JST |
| step | 381,197 |
| VE | 25.0 |
| fatigue | 16.1 |
| comfort zone | normal |
| current action | sleeping |
| sleep count | 159 |

`~/.seed0/memory/action_outcomes.db` より:

| 項目 | 値 |
|---|---:|
| AOR records | 6,877 |
| first step | 374,321 |
| latest step | 381,197 |
| first timestamp | 2026-05-06 01:22:49 |
| latest timestamp | 2026-05-06 11:35:11 |

## 3. 直近の観察予定

Google Calendar 登録済み:

- 2026-05-07 11:30-12:00: Seed0 AOR 24時間チェック
- 2026-05-09 11:30-12:00: Seed0 AOR 72時間チェック
- 2026-05-13 11:30-12:00: Seed0 AOR 7日チェック / 予測層判断

## 4. 次にやること

### AOR 24時間チェック

見るもの:

- AOR と `~/.seed0/logs/step_trace.jsonl` が step_id で 1:1 対応しているか
- AOR 書き込みが主処理を邪魔していないか
- DB 容量増加率
- `state_before` / `state_after` の記録品質
- 低VE / emergency、sleep、rest、sense_body が十分に記録されているか

### AOR 72時間チェック

見るもの:

- `rest` の VE 回復パターン
- `sense_body` が何を変え、何を変えないか
- 低VE / emergency で `sense_body` が続く時、その後どうなるか
- `sleep` 前後の VE / fatigue / memory 変化
- `purge_memory` の実効性

### AOR 7日チェック

判断すること:

- 行動ごとの結果に安定した傾向があるか
- 状態別に結果が変わるか
- 予測できる行動と予測しにくい行動が分かれるか
- 予測誤差を記録する価値があるか
- 環境2より先に read-only 予測層へ進むべきか

## 5. 触ってはいけないもの

観察期間中、以下は変更しない。

- 報酬関数
- 代謝パラメータ
- sleep / rest 閾値
- 行動プリミティブ
- 状態離散化キー
- LLM 接続
- 環境2（遊び場）投入

理由: 今見たいのは「正しい行動」ではなく、Seed0 が今の構造で何を経験しているかである。

## 6. 判断の原則

- 圧縮後の記憶より、実機状態を優先する
- 古い session log より、`CURRENT_STATE.md` と `ROADMAP_v3_draft.md` を優先する
- 大きな変更の前には必ず `docs/PRINCIPLES.md` と照合する
- 実装力で先に進みすぎない。第一原則に触る変更はオーナーと意図照合する

