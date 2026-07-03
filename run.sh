#!/usr/bin/env bash
# Ubuntu Remote Mac 起動スクリプト
set -euo pipefail
cd "$(dirname "$0")"

# Tk 8.6 以上を持つ python3 を選ぶ。
# - brew python は python-tk を入れないと _tkinter が無い
# - システム python (/usr/bin/python3) は Tk 8.5 で、最近の macOS ではウィンドウが真っ黒になる
pick_python() {
    for p in /opt/homebrew/bin/python3 \
             /usr/local/bin/python3 \
             /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 \
             python3 \
             /usr/bin/python3; do
        if command -v "$p" >/dev/null 2>&1 && \
           "$p" -c "import tkinter, sys; sys.exit(0 if tkinter.TkVersion >= 8.6 else 1)" >/dev/null 2>&1; then
            echo "$p"; return 0
        fi
    done
    echo python3   # 最後の手段
}

exec "$(pick_python)" ubuntu_remote.py "$@"
