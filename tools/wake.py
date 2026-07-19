#!/usr/bin/env python3
"""サスペンド中のマシンを Wake-on-LAN で起こす。

使い方:
    python3 tools/wake.py glavine

magic packet(FF×6 + MAC×16)をブロードキャストで送り、ssh (22) が開くまで
最大 60 秒ポーリングする。前提: 対象マシン側で WoL が有効になっていること
(NetworkManager: `802-3-ethernet.wake-on-lan: magic`。README 参照)。

MAC はサスペンド中は ARP で引けないため、ここに静的に登録しておく。
新しいマシンは HOSTS に 1 行足す(MAC は `ip link` で確認)。
"""
from __future__ import annotations

import socket
import sys
import time

# name: (MAC, ブロードキャストアドレス, 疎通確認先)
HOSTS = {
    "glavine": ("10:7c:61:45:68:41", "192.168.100.255", "192.168.100.201"),
}


def wake(name: str) -> int:
    if name not in HOSTS:
        print(f"'{name}' は未登録。登録済み: {', '.join(HOSTS)}")
        return 1
    mac, bcast, ip = HOSTS[name]
    payload = bytes.fromhex("FF" * 6 + mac.replace(":", "") * 16)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    for _ in range(3):  # 取りこぼし対策に複数発
        sock.sendto(payload, (bcast, 9))
        time.sleep(0.2)
    sock.close()
    print(f"magic packet 送信 → {name} ({mac})。ssh の応答を待ちます...")

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((ip, 22), timeout=2):
                print(f"✅ {name} が復帰しました({ip}:22 応答あり)。")
                return 0
        except OSError:
            time.sleep(2)
    print(f"❌ 60 秒待っても {ip}:22 が開きません。")
    print("   WoL がマシン側で無効(NetworkManager / BIOS)か、電源断の可能性。")
    return 1


if __name__ == "__main__":
    sys.exit(wake(sys.argv[1]) if len(sys.argv) > 1 else (print(__doc__), 1)[1])
