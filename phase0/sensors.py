"""
Seed0 Phase 0 — macOS センサー読取モジュール

Mac miniの「身体」からデータを読み取る。
macOSのネイティブコマンド（vm_stat, iostat, sysctl, powermetrics等）を使って
各種センサー値を取得する。

sudo不要なデータ → 常に取得
sudo必要なデータ（powermetrics） → オプショナル（--sudo フラグで有効化）
"""

import subprocess
import re
import os
import time
from typing import Optional


def _run(cmd: str, timeout: int = 5) -> Optional[str]:
    """シェルコマンドを実行し、標準出力を返す。失敗時はNoneを返す。"""
    try:
        # close_fds=True でPIDロックfd等の継承を防ぐ（Python 3.7+のデフォルトだが明示）
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout,
            close_fds=True
        )
        return result.stdout if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, Exception):
        return None


def _run_sudo(cmd: str, timeout: int = 10) -> Optional[str]:
    """sudoコマンドを実行。パスワードなしでsudoできる環境のみ動作する。"""
    return _run(f"sudo -n {cmd}", timeout=timeout)


# ─────────────────────────────────────────────
# メモリ情報
# ─────────────────────────────────────────────

def read_memory() -> dict:
    """
    vm_statとsysctlからメモリ情報を取得する。

    返すキー:
      memory_used_mb, memory_free_mb, memory_wired_mb,
      memory_compressed_mb, memory_active_mb, memory_inactive_mb,
      swap_used_mb, memory_pressure_percent
    """
    data = {}

    # vm_stat からページ情報を取得
    output = _run("vm_stat")
    if output:
        # ページサイズを取得（通常16384バイト）
        page_size_match = re.search(r"page size of (\d+) bytes", output)
        page_size = int(page_size_match.group(1)) if page_size_match else 16384
        to_mb = page_size / (1024 * 1024)

        def _pages(label):
            """vm_statの出力からページ数を抽出する"""
            match = re.search(rf'^{label}:\s+(\d+)', output, re.MULTILINE)
            return int(match.group(1)) if match else 0

        free = _pages("Pages free")
        active = _pages("Pages active")
        inactive = _pages("Pages inactive")
        wired = _pages("Pages wired down")
        compressed = _pages("Pages occupied by compressor")
        speculative = _pages("Pages speculative")

        data["memory_free_mb"] = round((free + speculative) * to_mb, 1)
        data["memory_active_mb"] = round(active * to_mb, 1)
        data["memory_inactive_mb"] = round(inactive * to_mb, 1)
        data["memory_wired_mb"] = round(wired * to_mb, 1)
        data["memory_compressed_mb"] = round(compressed * to_mb, 1)
        data["memory_used_mb"] = round((active + wired + compressed) * to_mb, 1)

    # スワップ使用量
    swap_output = _run("sysctl vm.swapusage")
    if swap_output:
        match = re.search(r"used\s*=\s*([\d.]+)M", swap_output)
        data["swap_used_mb"] = float(match.group(1)) if match else 0.0

    # メモリプレッシャー（macOS の memory_pressure コマンド）
    pressure_output = _run("memory_pressure 2>/dev/null || echo ''")
    if pressure_output:
        match = re.search(r"System-wide memory free percentage:\s+(\d+)%", pressure_output)
        if match:
            data["memory_pressure_percent"] = 100 - int(match.group(1))

    # メモリ圧縮率（圧縮されたメモリの総メモリに対する比率）
    if "memory_compressed_mb" in data:
        total_output = _run("sysctl hw.memsize")
        if total_output:
            match = re.search(r"hw\.memsize:\s+(\d+)", total_output)
            if match:
                total_mb = int(match.group(1)) / (1024 * 1024)
                data["memory_compressed_percent"] = round(
                    data["memory_compressed_mb"] / total_mb * 100, 2
                )

    return data


# ─────────────────────────────────────────────
# CPU情報
# ─────────────────────────────────────────────

def read_cpu() -> dict:
    """
    CPU使用率とロードアベレージを取得する。

    返すキー:
      cpu_usage_percent, cpu_user_percent, cpu_sys_percent, cpu_idle_percent,
      load_avg_1m, load_avg_5m, load_avg_15m
    """
    data = {}

    # top コマンドから全体のCPU使用率を取得
    output = _run("top -l 1 -n 0 -s 0")
    if output:
        # CPU usage: 5.26% user, 3.50% sys, 91.22% idle
        match = re.search(
            r"CPU usage:\s+([\d.]+)%\s+user,\s+([\d.]+)%\s+sys,\s+([\d.]+)%\s+idle",
            output
        )
        if match:
            user = float(match.group(1))
            sys_ = float(match.group(2))
            idle = float(match.group(3))
            data["cpu_user_percent"] = user
            data["cpu_sys_percent"] = sys_
            data["cpu_idle_percent"] = idle
            data["cpu_usage_percent"] = round(user + sys_, 2)

    # ロードアベレージ
    load_output = _run("sysctl vm.loadavg")
    if load_output:
        match = re.search(r"\{\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+\}", load_output)
        if match:
            data["load_avg_1m"] = float(match.group(1))
            data["load_avg_5m"] = float(match.group(2))
            data["load_avg_15m"] = float(match.group(3))

    return data


# ─────────────────────────────────────────────
# ディスク情報
# ─────────────────────────────────────────────

# ディスクI/O計算用の前回値を保持
_prev_disk_io = {"read_bytes": None, "write_bytes": None, "timestamp": None}

def read_disk() -> dict:
    """
    ディスク使用量とI/Oを取得する。

    返すキー:
      disk_total_gb, disk_used_gb, disk_free_gb, disk_usage_percent,
      disk_read_mb_s, disk_write_mb_s
    """
    data = {}

    # ディスク使用量（ルートボリューム）
    output = _run("df -m /")
    if output:
        lines = output.strip().split("\n")
        if len(lines) >= 2:
            parts = lines[1].split()
            if len(parts) >= 4:
                total_mb = int(parts[1])
                used_mb = int(parts[2])
                free_mb = int(parts[3])
                data["disk_total_gb"] = round(total_mb / 1024, 1)
                data["disk_used_gb"] = round(used_mb / 1024, 1)
                data["disk_free_gb"] = round(free_mb / 1024, 1)
                if total_mb > 0:
                    data["disk_usage_percent"] = round(used_mb / total_mb * 100, 1)

    # ディスクI/O（ioregから累積バイト数を取得し、前回との差分でレートを計算）
    io_output = _run("ioreg -c IOBlockStorageDriver -r -d 1")
    if io_output:
        read_match = re.search(r'"Bytes \(Read\)"=(\d+)', io_output)
        write_match = re.search(r'"Bytes \(Write\)"=(\d+)', io_output)
        now = time.time()

        if read_match and write_match:
            read_bytes = int(read_match.group(1))
            write_bytes = int(write_match.group(1))

            # 前回の値がある場合、差分からレートを計算
            if _prev_disk_io["timestamp"] is not None:
                dt = now - _prev_disk_io["timestamp"]
                if dt > 0:
                    data["disk_read_mb_s"] = round(
                        (read_bytes - _prev_disk_io["read_bytes"]) / dt / (1024 * 1024), 3
                    )
                    data["disk_write_mb_s"] = round(
                        (write_bytes - _prev_disk_io["write_bytes"]) / dt / (1024 * 1024), 3
                    )

            _prev_disk_io["read_bytes"] = read_bytes
            _prev_disk_io["write_bytes"] = write_bytes
            _prev_disk_io["timestamp"] = now

    return data


# ─────────────────────────────────────────────
# ネットワーク情報
# ─────────────────────────────────────────────

_prev_net = {"ibytes": None, "obytes": None, "timestamp": None}

def read_network() -> dict:
    """
    ネットワーク送受信量とアクティブ接続数を取得する。

    返すキー:
      net_recv_mb_s, net_send_mb_s, net_connections
    """
    data = {}
    now = time.time()

    # en0のバイトカウントを取得
    output = _run("netstat -ib -I en0")
    if output:
        lines = output.strip().split("\n")
        for line in lines:
            if "<Link#" in line:
                parts = line.split()
                # Name Mtu Network Address Ipkts Ierrs Ibytes Opkts Oerrs Obytes Coll
                if len(parts) >= 10:
                    try:
                        ibytes = int(parts[6])
                        obytes = int(parts[9])

                        # 前回の値と比較してレートを計算
                        if _prev_net["ibytes"] is not None and _prev_net["timestamp"] is not None:
                            dt = now - _prev_net["timestamp"]
                            if dt > 0:
                                data["net_recv_mb_s"] = round(
                                    (ibytes - _prev_net["ibytes"]) / dt / (1024 * 1024), 3
                                )
                                data["net_send_mb_s"] = round(
                                    (obytes - _prev_net["obytes"]) / dt / (1024 * 1024), 3
                                )

                        _prev_net["ibytes"] = ibytes
                        _prev_net["obytes"] = obytes
                        _prev_net["timestamp"] = now
                    except (ValueError, IndexError):
                        pass
                break

    # アクティブ接続数
    conn_output = _run("netstat -n 2>/dev/null | grep ESTABLISHED | wc -l")
    if conn_output:
        data["net_connections"] = int(conn_output.strip())

    return data


# ─────────────────────────────────────────────
# プロセス情報
# ─────────────────────────────────────────────

def read_processes() -> dict:
    """
    実行中プロセス数と稼働時間を取得する。

    返すキー:
      process_count, uptime_seconds
    """
    data = {}

    # プロセス数
    output = _run("ps aux | wc -l")
    if output:
        count = int(output.strip())
        data["process_count"] = max(0, count - 1)  # ヘッダ行を除く

    # 稼働時間（秒）
    output = _run("sysctl kern.boottime")
    if output:
        match = re.search(r"sec\s*=\s*(\d+)", output)
        if match:
            boot_time = int(match.group(1))
            data["uptime_seconds"] = int(time.time()) - boot_time

    return data


# ─────────────────────────────────────────────
# バックグラウンドプロセス活動
# ─────────────────────────────────────────────

def read_background_activity() -> dict:
    """
    macOSの主要なバックグラウンドプロセスのCPU消費を取得する。
    Seed0にとっては「内臓の活動量」。

    対象: Spotlight(mds), iCloud(bird/cloudd), Time Machine(backupd),
          バックグラウンド通信(nsurlsessiond), 画面描画(WindowServer)

    返すキー:
      background_cpu_percent — 対象プロセスのCPU使用率合計
    """
    data = {}

    # ps で対象プロセスのCPU%を取得し合計する
    output = _run(
        "ps -eo comm,%cpu"
    )
    if output:
        # 対象プロセス名（部分一致で検索）
        targets = [
            "mds_stores", "mds", "mdworker",  # Spotlight
            "backupd",                          # Time Machine
            "bird", "cloudd",                   # iCloud
            "nsurlsessiond",                    # バックグラウンド通信
            "WindowServer",                     # 画面描画
        ]
        total_cpu = 0.0
        for line in output.strip().split("\n"):
            parts = line.strip().rsplit(None, 1)
            if len(parts) == 2:
                comm = parts[0].strip()
                try:
                    cpu_val = float(parts[1])
                except ValueError:
                    continue
                # プロセス名がいずれかのターゲットに一致するか
                for target in targets:
                    if target in comm:
                        total_cpu += cpu_val
                        break
        data["background_cpu_percent"] = round(total_cpu, 2)

    return data


# ─────────────────────────────────────────────
# ユーザーアイドル時間
# ─────────────────────────────────────────────

def read_user_idle() -> dict:
    """
    キーボード/マウスの最終操作からの経過秒数を取得する。
    ioregのHIDIdleTime（ナノ秒単位）を秒に変換して返す。

    生の秒数をそのまま渡す。「いる/いない」の離散化はしない。
    意味づけはSeed0がbaseline学習で自分で発見する。

    返すキー:
      user_idle_seconds — 最終入力からの経過秒数
    """
    data = {}

    output = _run("ioreg -c IOHIDSystem | grep HIDIdleTime")
    if output:
        match = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', output)
        if match:
            # ナノ秒 → 秒に変換
            idle_ns = int(match.group(1))
            data["user_idle_seconds"] = round(idle_ns / 1_000_000_000, 1)

    return data


# ─────────────────────────────────────────────
# 電力・温度情報（powermetrics — sudo必要）
# ─────────────────────────────────────────────

def read_power_thermal(use_sudo: bool = False) -> dict:
    """
    powermetricsから電力と温度情報を取得する。
    sudoが必要。--sudo フラグが渡されたときのみ実行する。

    返すキー:
      cpu_power_mw, gpu_power_mw, ane_power_mw, package_power_mw,
      cpu_freq_mhz, gpu_freq_mhz,
      thermal_pressure
    """
    if not use_sudo:
        return {}

    data = {}

    # powermetrics で CPU/GPU/ANE の電力と周波数を取得
    output = _run_sudo(
        "powermetrics -s cpu_power,gpu_power,ane_power,thermal -i 1000 -n 1",
        timeout=15
    )
    if output:
        # CPU Power: 123 mW
        for label, key in [
            ("CPU Power", "cpu_power_mw"),
            ("GPU Power", "gpu_power_mw"),
            ("ANE Power", "ane_power_mw"),
            ("Combined Power \\(CPU \\+ GPU \\+ ANE\\)", "package_power_mw"),
            ("Package Power", "package_power_mw"),
        ]:
            match = re.search(rf"{label}:\s+([\d.]+)\s*mW", output)
            if match:
                data[key] = float(match.group(1))

        # E-Cluster/P-Cluster HW active frequency
        freq_match = re.search(r"P-Cluster HW active frequency:\s+(\d+)\s*MHz", output)
        if freq_match:
            data["cpu_freq_mhz"] = int(freq_match.group(1))

        # GPU active frequency
        gpu_freq_match = re.search(r"GPU HW active frequency:\s+(\d+)\s*MHz", output)
        if gpu_freq_match:
            data["gpu_freq_mhz"] = int(gpu_freq_match.group(1))

        # Thermal pressure
        thermal_match = re.search(r"Thermal pressure:\s+(\w+)", output)
        if thermal_match:
            data["thermal_pressure"] = thermal_match.group(1)

    return data


# ─────────────────────────────────────────────
# 全センサー統合読取
# ─────────────────────────────────────────────

def read_all_sensors(use_sudo: bool = False) -> dict:
    """
    全センサーデータを一括取得して辞書で返す。

    取得できなかった値はキーごと省略される（NULLとしてDBに記録される）。
    """
    data = {}
    data.update(read_memory())             # メモリ + 圧縮率
    data.update(read_cpu())                # CPU + ロードアベレージ
    data.update(read_disk())               # ディスク容量 + I/O（read/write）
    data.update(read_network())            # ネットワーク送受信
    data.update(read_processes())          # プロセス数 + 稼働時間
    data.update(read_background_activity())  # バックグラウンドプロセスCPU
    data.update(read_user_idle())            # ユーザーアイドル時間
    data.update(read_power_thermal(use_sudo=use_sudo))  # 電力・温度（sudo時のみ）
    return data


# ─────────────────────────────────────────────
# テスト用：直接実行すると1回分のデータを表示
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import json
    print("=== Seed0 センサー読取テスト ===")
    result = read_all_sensors(use_sudo=False)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\n取得できたパラメータ数: {len(result)}")
