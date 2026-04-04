"""
Seed0 Phase 0 — SQLite 保存モジュール

センサーデータをSQLiteデータベースに記録する。
データベースは ~/.seed0/phase0/body_data.db に保存される。

設計方針:
- カラムは動的に管理する（新しいセンサーが追加されても自動対応）
- タイムスタンプは常にUTCで記録
- データは追記のみ（既存データを上書きしない）
"""

import sqlite3
import os
import csv
from datetime import datetime, timezone
from typing import Optional


# データベースのデフォルトパス
DEFAULT_DB_PATH = os.path.expanduser("~/.seed0/phase0/body_data.db")

# テーブル名
TABLE_NAME = "body_sensor_readings"

# 記録する全カラムの定義（順序を保証するため明示的にリスト化）
SENSOR_COLUMNS = [
    # メモリ系
    "memory_used_mb",
    "memory_free_mb",
    "memory_active_mb",
    "memory_inactive_mb",
    "memory_wired_mb",
    "memory_compressed_mb",
    "swap_used_mb",
    "memory_pressure_percent",
    # CPU系
    "cpu_usage_percent",
    "cpu_user_percent",
    "cpu_sys_percent",
    "cpu_idle_percent",
    "load_avg_1m",
    "load_avg_5m",
    "load_avg_15m",
    # ディスク系
    "disk_total_gb",
    "disk_used_gb",
    "disk_free_gb",
    "disk_usage_percent",
    "disk_read_mb_s",
    # ネットワーク系
    "net_recv_mb_s",
    "net_send_mb_s",
    "net_connections",
    # プロセス系
    "process_count",
    "uptime_seconds",
    # 電力・温度系（sudo必要）
    "cpu_power_mw",
    "gpu_power_mw",
    "ane_power_mw",
    "package_power_mw",
    "cpu_freq_mhz",
    "gpu_freq_mhz",
    "thermal_pressure",
]


class SensorStorage:
    """センサーデータのSQLite保存を管理するクラス"""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._ensure_directory()
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")  # 並行読み書きに強い
        self._create_table()

    def _ensure_directory(self):
        """データベースの親ディレクトリが存在しなければ作成する"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

    def _create_table(self):
        """センサーデータ用のテーブルを作成する（存在しなければ）"""
        columns = ",\n    ".join(
            f"{col} REAL" if col != "thermal_pressure" else f"{col} TEXT"
            for col in SENSOR_COLUMNS
        )
        sql = f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            {columns}
        )
        """
        self.conn.execute(sql)

        # タイムスタンプにインデックスを作成
        self.conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_timestamp
            ON {TABLE_NAME} (timestamp)
        """)
        self.conn.commit()

    def insert(self, sensor_data: dict):
        """
        センサーデータを1行挿入する。

        sensor_data: sensors.read_all_sensors() の返り値
        """
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        # SENSOR_COLUMNSの順でデータを取り出す（存在しないキーはNone）
        values = [sensor_data.get(col) for col in SENSOR_COLUMNS]

        placeholders = ", ".join(["?"] * (1 + len(SENSOR_COLUMNS)))
        columns = ", ".join(["timestamp"] + SENSOR_COLUMNS)

        sql = f"INSERT INTO {TABLE_NAME} ({columns}) VALUES ({placeholders})"
        self.conn.execute(sql, [now] + values)
        self.conn.commit()

    def count(self) -> int:
        """記録済みのデータ行数を返す"""
        cursor = self.conn.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}")
        return cursor.fetchone()[0]

    def get_time_range(self) -> tuple:
        """最初と最後のタイムスタンプを返す"""
        cursor = self.conn.execute(
            f"SELECT MIN(timestamp), MAX(timestamp) FROM {TABLE_NAME}"
        )
        return cursor.fetchone()

    def get_summary(self) -> dict:
        """
        全パラメータのmin / max / avg を計算して返す。
        --summary オプション用。
        """
        summary = {}
        for col in SENSOR_COLUMNS:
            if col == "thermal_pressure":
                # テキスト列は最頻値を出す
                cursor = self.conn.execute(f"""
                    SELECT {col}, COUNT(*) as cnt
                    FROM {TABLE_NAME}
                    WHERE {col} IS NOT NULL
                    GROUP BY {col}
                    ORDER BY cnt DESC
                    LIMIT 1
                """)
                row = cursor.fetchone()
                if row:
                    summary[col] = {"most_common": row[0], "count": row[1]}
            else:
                cursor = self.conn.execute(f"""
                    SELECT
                        MIN({col}),
                        MAX({col}),
                        ROUND(AVG({col}), 2)
                    FROM {TABLE_NAME}
                    WHERE {col} IS NOT NULL
                """)
                row = cursor.fetchone()
                if row and row[0] is not None:
                    summary[col] = {
                        "min": row[0],
                        "max": row[1],
                        "avg": row[2],
                    }

        return summary

    def get_latest(self) -> Optional[dict]:
        """最新の1行を辞書で返す"""
        cursor = self.conn.execute(
            f"SELECT timestamp, {', '.join(SENSOR_COLUMNS)} "
            f"FROM {TABLE_NAME} ORDER BY id DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if not row:
            return None

        result = {"timestamp": row[0]}
        for i, col in enumerate(SENSOR_COLUMNS):
            result[col] = row[i + 1]
        return result

    def export_csv(self, output_path: str):
        """全データをCSVファイルにエクスポートする"""
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        cursor = self.conn.execute(
            f"SELECT timestamp, {', '.join(SENSOR_COLUMNS)} "
            f"FROM {TABLE_NAME} ORDER BY id"
        )

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp"] + SENSOR_COLUMNS)
            for row in cursor:
                writer.writerow(row)

    def close(self):
        """データベース接続を閉じる"""
        self.conn.close()
