# Seed0 Context Protocol

> 作成日: 2026-05-06
> 目的: セッション圧縮・新セッション・コンテキスト喪失後に、Codex が古い文脈や圧縮記憶に引きずられず現在地へ戻るための復帰手順。

## 1. 基本方針

圧縮後の記憶を信用しすぎない。

Seed0 は長期プロジェクトであり、過去の判断・履歴・現在地が分離している。圧縮後の Codex は、古い「現在地」を最新と誤認する可能性がある。

したがって、復帰時は必ず以下の順で確認する。

## 2. 復帰時の優先順位

1. 実機状態
   - `~/.seed0/status.json`
   - `~/.seed0/logs/agent.log`
   - `~/.seed0/logs/step_trace.jsonl`
   - `~/.seed0/memory/action_outcomes.db`
   - `git status`
2. 現在地文書
   - `docs/CURRENT_STATE.md`
   - `docs/ROADMAP_v3_draft.md`
   - `AGENTS.md`
3. 原則文書
   - `docs/PRINCIPLES.md`
   - `docs/design_partner_guide.md`
4. 直近 session log
   - `docs/session_log_2026-05-05_phase_d_layer_specification.md`
   - `docs/session_log_2026-05-05_aor_implementation_completion.md`
5. 履歴文書
   - `docs/ROADMAP.md`
   - `docs/phase1_retrospective_2026-05-01.md`
   - `docs/known_issues_2026-05-01.md`
   - `docs/contamination_evaluation_2026-05-02.md`
6. 圧縮された会話記憶

圧縮された会話記憶は最下位とする。「覚えている気がする」より「確認した」を優先する。

## 3. 新セッション開始時チェック

新セッションまたは圧縮後に Seed0 の作業へ戻る時は、最初に以下を行う。

### 3.1 文書確認

読む:

- `AGENTS.md`
- `docs/CURRENT_STATE.md`
- `docs/ROADMAP_v3_draft.md`
- `docs/design_partner_guide.md`

### 3.2 実機確認

確認する:

```bash
python3 - <<'PY'
import json, os, datetime
p=os.path.expanduser('~/.seed0/status.json')
if os.path.exists(p):
    d=json.load(open(p))
    print(datetime.datetime.fromtimestamp(d['timestamp']).isoformat())
    print(json.dumps(d, ensure_ascii=False, indent=2))
PY
```

必要に応じて:

```bash
git status --short
```

AOR の作業なら:

```bash
sqlite3 ~/.seed0/memory/action_outcomes.db \
  "select count(*), min(step_id), max(step_id), min(ts), max(ts) from action_outcomes;"
```

## 4. 判断前の安全確認

以下に触る変更は、実装前に必ずオーナーと意図照合する。

- 報酬関数
- 代謝パラメータ
- comfort zone 関連パラメータ
- 状態離散化キー
- 行動プリミティブ
- LLM 接続
- 環境2以降への進行
- Seed0 の主体性に関わる構造変更

上記に該当しない、観察・レポート・テスト・小さく可逆な整理は Codex が自走してよい。

## 5. 圧縮後に起きやすい失敗

### 古い現在地を最新扱いする

例: 「Seed0 は停止中」と思い込む。

対策: `status.json` と `CURRENT_STATE.md` を確認する。

### 履歴文書を現在方針として読む

例: `docs/ROADMAP.md` v2 の「フェーズD」を現在計画として扱う。

対策: `ROADMAP_v3_draft.md` を優先し、v2 は履歴として扱う。

### 綺麗な物語へ急ぐ

例: 低VE時の `sense_body` 偏重を「意味ある創発」と断定する。

対策: AOR / step_trace / DB の数値で確認し、観察と解釈を分ける。

### 実装力で先に進みすぎる

例: 予測層をすぐ行動選択へ接続する。

対策: read-only、観察、予測誤差記録の順に進める。報酬や行動にはすぐ接続しない。

## 6. セッション終了時の申し送り

重要な作業をした日は、短い session log または `CURRENT_STATE.md` 更新を残す。

最低限書く:

- 今日決めたこと
- 実装したこと
- 未決のこと
- 次回最初に確認すること
- 触ってはいけないもの

## 7. Google Calendar を外部記憶として使う

時間ベースの観察予定は Google Calendar に置く。

現在登録済み:

- 2026-05-07 11:30: Seed0 AOR 24時間チェック
- 2026-05-09 11:30: Seed0 AOR 72時間チェック
- 2026-05-13 11:30: Seed0 AOR 7日チェック / 予測層判断

カレンダーは会話記憶より信頼できる外部記憶として扱う。

## 8. 重要な姿勢

Codex は、オーナーの厳密な実装指示を待つだけの存在ではない。意図を設計・実装・検証へ翻訳する。

ただし、Seed0 の北極星を勝手に書き換えない。

> Seed0 は、データ少佐そのものを作るプロジェクトではない。
> データ少佐のような存在が育ちうる種を作るプロジェクトである。

この前提が揺れたら、作業を止めてオーナーと確認する。

