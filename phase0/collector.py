#!/usr/bin/env python3
"""
Seed0 Phase 0 — データ収集スクリプト（メイン）

Mac miniの「身体」を5秒ごとに観察し、SQLiteに記録する。
Phase 0ではデータを集めるだけ。行動は一切しない。

使い方:
  python3 phase0/collector.py                    # 5秒間隔で収集開始
  python3 phase0/collector.py --interval 10      # 10秒間隔
  python3 phase0/collector.py --sudo             # powermetrics有効（電力・温度）
  python3 phase0/collector.py --summary          # 収集済みデータの統計表示
  python3 phase0/collector.py --export csv       # CSVエクスポート
  python3 phase0/collector.py --quiet            # ログ出力を抑制

Ctrl+C で安全に停止。データは保持される。
"""

import argparse
import signal
import sys
import time
from datetime import datetime, timezone

# 同じディレクトリのモジュールをインポート
from sensors import read_all_sensors
from storage import SensorStorage, DEFAULT_DB_PATH


def format_duration(seconds: int) -> str:
    """秒数を「Xd Xh Xm Xs」形式に変換する"""
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def show_summary(storage: SensorStorage):
    """収集済みデータの統計サマリーを表示する"""
    count = storage.count()
    if count == 0:
        print("データがありません。まず収集を実行してください。")
        return

    first, last = storage.get_time_range()
    print(f"\n{'='*60}")
    print(f"  Seed0 Phase 0 — 身体データサマリー")
    print(f"{'='*60}")
    print(f"  記録数:     {count:,} 件")
    print(f"  期間:       {first}  〜  {last}")
    print(f"  DB:         {storage.db_path}")
    print(f"{'='*60}\n")

    summary = storage.get_summary()
    latest = storage.get_latest()

    # カテゴリ別に表示
    categories = {
        "メモリ": [
            "memory_used_mb", "memory_free_mb", "memory_wired_mb",
            "memory_compressed_mb", "swap_used_mb", "memory_pressure_percent"
        ],
        "CPU": [
            "cpu_usage_percent", "cpu_user_percent", "cpu_sys_percent",
            "load_avg_1m", "load_avg_5m", "load_avg_15m"
        ],
        "ディスク": [
            "disk_used_gb", "disk_free_gb", "disk_usage_percent", "disk_read_mb_s"
        ],
        "ネットワーク": [
            "net_recv_mb_s", "net_send_mb_s", "net_connections"
        ],
        "プロセス": [
            "process_count", "uptime_seconds"
        ],
        "電力・温度 (sudo)": [
            "cpu_power_mw", "gpu_power_mw", "ane_power_mw",
            "package_power_mw", "cpu_freq_mhz", "gpu_freq_mhz",
            "thermal_pressure"
        ],
    }

    for category, keys in categories.items():
        has_data = any(k in summary for k in keys)
        if not has_data:
            continue

        print(f"  [{category}]")
        print(f"  {'パラメータ':<30s} {'min':>10s} {'avg':>10s} {'max':>10s} {'現在値':>10s}")
        print(f"  {'-'*70}")

        for key in keys:
            if key not in summary:
                continue
            s = summary[key]
            if isinstance(s, dict) and "min" in s:
                current = latest.get(key, "-") if latest else "-"
                if current is not None and isinstance(current, float):
                    current = f"{current:.1f}"
                print(f"  {key:<30s} {s['min']:>10.1f} {s['avg']:>10.1f} {s['max']:>10.1f} {str(current):>10s}")
            elif isinstance(s, dict) and "most_common" in s:
                current = latest.get(key, "-") if latest else "-"
                print(f"  {key:<30s} {'':>10s} {s['most_common']:>10s} {'':>10s} {str(current):>10s}")
        print()


def show_startup_info(storage: SensorStorage, interval: int, use_sudo: bool):
    """起動時の情報を表示する"""
    count = storage.count()
    print(f"\n{'='*60}")
    print(f"  Seed0 Phase 0 — 身体観察を開始します")
    print(f"{'='*60}")
    print(f"  収集間隔:   {interval} 秒")
    print(f"  sudo:       {'有効' if use_sudo else '無効'}")
    print(f"  DB:         {storage.db_path}")
    print(f"  既存データ: {count:,} 件")
    print(f"{'='*60}")
    print(f"  Ctrl+C で安全に停止できます")
    print(f"{'='*60}\n")


def show_shutdown_info(storage: SensorStorage, readings_this_session: int):
    """停止時の情報を表示する"""
    count = storage.count()
    print(f"\n{'='*60}")
    print(f"  Seed0 Phase 0 — 身体観察を終了します")
    print(f"{'='*60}")
    print(f"  今回の記録: {readings_this_session:,} 件")
    print(f"  累計:       {count:,} 件")

    first, last = storage.get_time_range()
    if first and last:
        print(f"  期間:       {first}  〜  {last}")

    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Seed0 Phase 0 — Mac miniの身体データを収集する"
    )
    parser.add_argument(
        "--interval", type=int, default=5,
        help="収集間隔（秒）。デフォルト: 5"
    )
    parser.add_argument(
        "--sudo", action="store_true",
        help="powermetricsを使用して電力・温度データも収集する"
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="定期的なステータス表示を抑制する"
    )
    parser.add_argument(
        "--summary", action="store_true",
        help="収集済みデータの統計サマリーを表示して終了"
    )
    parser.add_argument(
        "--export", type=str, metavar="FORMAT",
        help="データをエクスポートする。現在は 'csv' のみ対応"
    )
    parser.add_argument(
        "--db", type=str, default=DEFAULT_DB_PATH,
        help=f"データベースファイルのパス。デフォルト: {DEFAULT_DB_PATH}"
    )

    args = parser.parse_args()

    # ストレージを初期化
    storage = SensorStorage(db_path=args.db)

    # --summary: サマリー表示して終了
    if args.summary:
        show_summary(storage)
        storage.close()
        return

    # --export: エクスポートして終了
    if args.export:
        if args.export.lower() == "csv":
            output_path = os.path.join(
                os.path.dirname(args.db),
                f"body_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            )
            storage.export_csv(output_path)
            print(f"CSVエクスポート完了: {output_path}")
            print(f"  {storage.count():,} 件のデータを出力しました")
        else:
            print(f"未対応のフォーマット: {args.export}")
            print("対応フォーマット: csv")
        storage.close()
        return

    # ─── 収集ループ ───

    show_startup_info(storage, args.interval, args.sudo)

    readings_this_session = 0
    last_status_time = 0
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        while running:
            loop_start = time.time()

            # センサー読取
            try:
                data = read_all_sensors(use_sudo=args.sudo)
                storage.insert(data)
                readings_this_session += 1
            except Exception as e:
                if not args.quiet:
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"[{now_str}] センサー読取エラー: {e}")

            # 1分ごとにステータスを表示（--quiet でなければ）
            now = time.time()
            if not args.quiet and (now - last_status_time) >= 60:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                total = storage.count()
                # 直近のデータからハイライトを作成
                cpu_str = f"CPU: {data.get('cpu_usage_percent', '?')}%"
                mem_pct = ""
                if data.get("memory_used_mb") and data.get("memory_free_mb"):
                    total_mem = data["memory_used_mb"] + data["memory_free_mb"]
                    if total_mem > 0:
                        mem_pct = f", MEM: {data['memory_used_mb']/total_mem*100:.0f}%"
                disk_str = ""
                if data.get("disk_read_mb_s") is not None:
                    disk_str = f", DISK I/O: {data['disk_read_mb_s']:.1f}MB/s"
                load_str = ""
                if data.get("load_avg_1m") is not None:
                    load_str = f", LOAD: {data['load_avg_1m']:.2f}"

                print(f"[{now_str}] {total:,} readings. {cpu_str}{mem_pct}{disk_str}{load_str}")
                last_status_time = now

            # 次のサイクルまで待機
            elapsed = time.time() - loop_start
            sleep_time = max(0, args.interval - elapsed)
            if sleep_time > 0 and running:
                # sleep を小分けにして、Ctrl+C への応答を速くする
                end_time = time.time() + sleep_time
                while time.time() < end_time and running:
                    time.sleep(min(0.5, end_time - time.time()))

    finally:
        show_shutdown_info(storage, readings_this_session)
        storage.close()


# osモジュールのインポート（exportで使用）
import os

if __name__ == "__main__":
    main()
