# Seed0 — 代謝AI

## プロジェクト概要
Mac miniを「身体」として生きる代謝AI。詳細はREADME.mdとdocs/PRINCIPLES.mdを参照。

## 第一原則
「Seed0に与えるのは構造だけ。動機はすべて構造から生まれなければならない。」

## 開発環境
- ハードウェア: Mac mini M4 / 24GB / 512GB SSD
- 言語: Python
- DB: SQLite
- リポジトリ: https://github.com/nopposanhaveadream-glitch/Seed

## コーディング規約
- コメントは日本語で書く
- 非エンジニアが読む可能性があるため、分かりやすく書く
- 外部ライブラリの依存は最小限にする
- macOS固有のコード（sensors.py）とOS非依存のコード（それ以外）を分離する

## 現在のフェーズ
Phase 0: データ収集中。phase0/collector.py がバックグラウンドで稼働中。
このプロセスを止めないこと。

## ディレクトリ構造
- phase0/ — センサーデータ収集（現在稼働中）
- core/ — 代謝・エージェント（今後実装）
- sandbox/ — 遊び場（今後実装）
- config/ — 設定ファイル
- docs/ — 設計文書

## 重要な制約
- IMPORTANT: phase0/collector.py の稼働中プロセスを絶対に止めない
- IMPORTANT: 設計変更はPRINCIPLES.mdの8原則と照合してから実施する
- comfort_zone.yaml はPhase 0のデータ分析後に更新する（今は触らない）
