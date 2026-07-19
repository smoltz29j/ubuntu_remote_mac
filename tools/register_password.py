#!/usr/bin/env python3
"""プロファイルのパスワードを、接続先の PAM で検証してから Keychain に登録する。

誤った値を保存すると xrdp 側は pam_authenticate failed としか言わず、原因の切り分けに
時間を溶かす(2026-07-19 の glavine で実証済み)。このツールは ssh 経由で接続先の
`su <ユーザー名>` にパスワードを直接突き合わせ、**通った値だけ**を保存する。

使い方:
    python3 tools/register_password.py <プロファイル名> [ssh先]

    <プロファイル名>  profiles.json の name(例: Glavine)
    [ssh先]           省略時はプロファイルの host へ ssh する。~/.ssh/config の
                      エイリアス(例: glavine)を使いたいときに指定する。

パスワードは画面に表示されず(getpass)、ps にも出ない(ssh の stdin 経由のみ)。
RDP のセッションウィンドウで手入力すると JIS/ABC 配列ずれで記号が化けることがあるため、
登録はローカルのターミナルで行うこと。
"""
from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ubuntu_remote as ur

# 接続先で su を pty 駆動するチェッカー。su は同一ユーザーからでもパスワードを
# 求める(root からは求めない)ので、必ず一般ユーザーで ssh すること。
PAMCHECK = r'''
import os, pty, sys, time
user = sys.argv[1]
pw = sys.stdin.readline().rstrip("\n")
pid, fd = pty.fork()
if pid == 0:
    os.execvp("su", ["su", user, "-c", "true"])
time.sleep(0.7)
os.write(fd, (pw + "\n").encode())
try:
    while os.read(fd, 4096):
        pass
except OSError:
    pass
_, status = os.waitpid(pid, 0)
print("PAM_OK" if os.waitstatus_to_exitcode(status) == 0 else "PAM_NG")
'''


def main() -> int:
    if len(sys.argv) < 2:
        profiles = json.load(open(ur.PROFILES_PATH, encoding="utf-8"))
        print(__doc__)
        print("登録済みプロファイル:")
        for p in profiles:
            print(f"  {p['name']:12} {p['host']}:{p['port']}  user={p['username']}")
        return 1

    name = sys.argv[1]
    profiles = json.load(open(ur.PROFILES_PATH, encoding="utf-8"))
    matches = [p for p in profiles if p["name"] == name]
    if not matches:
        print(f"プロファイル '{name}' が見つかりません。")
        return 1
    profile = matches[0]
    user = profile["username"]
    ssh_host = sys.argv[2] if len(sys.argv) > 2 else profile["host"]

    pw = getpass.getpass(f"{name} ({user}@{profile['host']}) のパスワード: ")
    if not pw:
        print("入力が空です。中止しました。")
        return 1

    print(f"入力を受け取りました({len(pw)} 文字)。{ssh_host} の PAM で検証します...")
    remote = f"/tmp/pamcheck-{uuid.uuid4().hex[:8]}.py"
    ssh = ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", ssh_host]
    up = subprocess.run(ssh + [f"cat > {remote}"], input=PAMCHECK, text=True)
    if up.returncode != 0:
        print(f"❌ {ssh_host} に ssh できません(鍵認証が必要)。")
        return 1
    run = subprocess.run(
        ssh + [f"python3 {remote} {user}; rm -f {remote}"],
        input=pw + "\n", capture_output=True, text=True)

    if "PAM_OK" in run.stdout:
        ur.keychain_set_password(profile["id"], pw)
        print(f"✅ 検証に成功したので Keychain に保存しました({name} / {user})。")
        return 0
    print(f"❌ このパスワードでは {user} の認証が通りません。保存していません。")
    print("   接続先のコンソールでロック解除に使う値を確認してください。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
