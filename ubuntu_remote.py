#!/usr/bin/env python3
# Ubuntu Remote Mac — Ubuntu マシン(xrdp)へ接続するリモートデスクトップランチャー
#
# 姉妹プロジェクト ~/claude/ubuntu_remote (Windows / WPF + RDP ActiveX) の macOS 版。
# macOS には埋め込み可能な RDP コントロールが無いため、tkinter のプロファイル管理 UI から
# FreeRDP (xfreerdp) を子プロセスとして起動する軽量ランチャー構成をとる。
#
# - プロファイル: ~/Library/Application Support/UbuntuRemote/profiles.json(パスワードは含めない)
# - パスワード:   macOS Keychain(service=UbuntuRemote, account=プロファイルID)
# - ログ:         ~/Library/Application Support/UbuntuRemote/app.log(xfreerdp の出力もここへ)

from __future__ import annotations  # システム python3 (3.9) では X | Y 注釈にこれが必須

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import tkinter as tk
from tkinter import ttk, messagebox

APP_NAME = "UbuntuRemote"
SUPPORT_DIR = os.path.expanduser(f"~/Library/Application Support/{APP_NAME}")
PROFILES_PATH = os.path.join(SUPPORT_DIR, "profiles.json")
LOG_PATH = os.path.join(SUPPORT_DIR, "app.log")
KEYCHAIN_SERVICE = APP_NAME

RETRY_MAX = 5          # 非ユーザー起因の切断をリトライする上限(Windows 版と同じ)
RETRY_INTERVAL = 3.0   # リトライ間隔(秒)
STABLE_UPTIME = 60.0   # この秒数以上続いたセッションが切れたらリトライ回数を数え直す

# sdl-freerdp のユーザー起因の exit code(SDL クライアント自身もエラー表示しない集合)。
# 0=正常終了, 1=DISCONNECT, 2=LOGOFF(リモートでログアウト), 11=DISCONNECT_BY_USER,
# 145=CONNECT_CANCELLED。これらはリトライしない。
# 注意: ウィンドウを閉じたときの実際の exit は 131 (CONN_FAILED) で、ネットワーク断で
# 内蔵再接続に失敗したときと同じ汎用値(FreeRDP 3.27 のソースとログで確認)。
# 131 はログの中断マーカーで区別する(Session._user_aborted_in_log)。
USER_EXIT_CODES = {0, 1, 2, 11, 145}
EXIT_CONN_FAILED = 131

# 実際の画面サイズは main() で tkinter から取得して上書きする
SCREEN_SIZE = (1920, 1080)

_log_lock = threading.Lock()


def log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n"
    with _log_lock:
        os.makedirs(SUPPORT_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)


def find_xfreerdp() -> str | None:
    # sdl-freerdp を最優先: brew の xfreerdp は X11(XQuartz)が必要だが、
    # SDL クライアントは macOS でネイティブに動く
    for name in ("sdl-freerdp", "xfreerdp3", "xfreerdp"):
        path = shutil.which(name)
        if path:
            return path
        for prefix in ("/opt/homebrew/bin", "/usr/local/bin"):
            candidate = os.path.join(prefix, name)
            if os.access(candidate, os.X_OK):
                return candidate
    return None


# ---------------------------------------------------------------- プロファイル

def default_profile() -> dict:
    return {
        "id": str(uuid.uuid4()),
        "name": "",
        "host": "",
        "port": 3389,
        "username": "",
        "domain": "",
        "redirect_clipboard": True,
        "redirect_drives": False,
        "use_nla": False,  # Ubuntu の xrdp は通常 NLA 非対応のため既定オフ
    }


def display_text(profile: dict) -> str:
    return profile["name"].strip() or f"{profile['username']}@{profile['host']}"


def load_profiles() -> list[dict]:
    try:
        with open(PROFILES_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, OSError) as e:
        log(f"profiles.json の読み込みに失敗: {e}")
        return []
    # 将来フィールドを増やしたとき古い JSON でも欠損キーで落ちないよう既定値に重ねる
    return [{**default_profile(), **p} for p in raw]


def save_profiles(profiles: list[dict]) -> None:
    os.makedirs(SUPPORT_DIR, exist_ok=True)
    tmp = PROFILES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(profiles, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PROFILES_PATH)


# ---------------------------------------------------------------- Keychain
# パスワードは Keychain のみに保存する。設定時は `security -i`(stdin からコマンドを
# 読むモード)を使い、平文パスワードがプロセス一覧(ps)に一瞬も出ないようにする。

def _security_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def keychain_set_password(profile_id: str, password: str) -> bool:
    command = " ".join([
        "add-generic-password", "-U",
        "-s", _security_quote(KEYCHAIN_SERVICE),
        "-a", _security_quote(profile_id),
        "-w", _security_quote(password),
    ]) + "\n"
    r = subprocess.run(["security", "-i"], input=command,
                       capture_output=True, text=True)
    if r.returncode != 0:
        log(f"Keychain への保存に失敗 (rc={r.returncode}): {r.stderr.strip()}")
        return False
    return True


def keychain_get_password(profile_id: str) -> str | None:
    # -w は非 ASCII パスワードを hex で出力し ASCII と区別できないため -g を使う。
    # -g の password: 行は 非ASCII → `password: 0x<HEX>  "..."`、ASCII → `password: "<生の値>"`
    # で常に区別可能(hex に見える ASCII パスワードも引用形式になる)。
    r = subprocess.run(
        ["security", "find-generic-password",
         "-s", KEYCHAIN_SERVICE, "-a", profile_id, "-g"],
        capture_output=True, text=True)
    if r.returncode != 0:  # 44 = 未登録
        return None
    for line in r.stderr.splitlines():
        if not line.startswith("password:"):
            continue
        m = re.match(r'^password: 0x([0-9A-Fa-f]+)', line)
        if m:
            return bytes.fromhex(m.group(1)).decode("utf-8")
        m = re.match(r'^password: "(.*)"$', line, re.DOTALL)
        if m:
            return m.group(1)
        return ""  # `password:` のみ = 空パスワード
    return None


def keychain_delete_password(profile_id: str) -> None:
    subprocess.run(
        ["security", "delete-generic-password",
         "-s", KEYCHAIN_SERVICE, "-a", profile_id],
        capture_output=True, text=True)


# ---------------------------------------------------------------- セッション

def build_rdp_args(profile: dict) -> list[str]:
    """実行ファイル名とパスワードを除いた sdl-freerdp の引数リスト。"""
    args = [
        f"/v:{profile['host']}:{profile['port']}",
        f"/u:{profile['username']}",
        f"/t:{display_text(profile)}",
        "/cert:ignore",           # xrdp は自己署名証明書のため検証しない
        # 解像度は画面サイズから明示計算(% 指定は SDL クライアントでは効かない)。
        # xrdp 0.9 系は Display Control 非対応でリサイズしても解像度が変わらないため、
        # /smart-sizing でウィンドウサイズへの拡縮に対応する
        # (+dynamic-resolution とは同時指定不可なので使わない)。
        f"/size:{int(SCREEN_SIZE[0] * 0.92)}x{int(SCREEN_SIZE[1] * 0.92)}",
        "/smart-sizing",
        "/sound",                 # 音声リダイレクト(サーバー側は pipewire-module-xrdp 導入済み)
        "/network:lan",
        # GFX パイプライン。xrdp 0.10 は AVC444 明示で H.264 になる(無指定の /gfx だと
        # RFX progressive 止まり。サーバーログ「Matched H264 mode」で確認済み)
        "/gfx:AVC444",
        "+rfx",                   # GFX 非対応の xrdp 0.9 系向けフォールバック(0.9 では実質最速)
        "-nsc",                   # NSC は ARM Mac ビルドで未最適化のため使わせない
        # 日本語入力はリモートの ibus-mozc に行わせる(Mac 側 IME を使う
        # /kbd:unicode は SDL クライアントのセッションウィンドウでは機能しなかった)。
        # 無指定だと macOS の入力ソース(ABC)から US 配列として申告され記号配置がずれるので、
        # 日本語配列を明示する。なお IME の切り替えは かな/英数 キーでは不可能
        # (macOS が IME 層より手前で消費し RDP に一切流れない)。Ctrl+Shift+; を
        # Karabiner で合成して送る構成。詳細は CLAUDE.md「日本語入力」参照。
        "/kbd:layout:0x00000411",
        "+auto-reconnect",
        f"/auto-reconnect-max-retries:{RETRY_MAX}",
        "+clipboard" if profile["redirect_clipboard"] else "-clipboard",
    ]
    # 既定はプロトコル自動交渉(NLA 必須のサーバーにも TLS のみのサーバーにも繋がる)。
    # チェックが入っているときだけ NLA を強制する。
    if profile["use_nla"]:
        args.append("/sec:nla")
    if profile["redirect_drives"]:
        args.append("+drives")
    if profile["domain"].strip():
        args.append(f"/d:{profile['domain'].strip()}")
    return args


class Session:
    """1 プロファイル分の xfreerdp プロセスと自動再接続を管理する。

    FreeRDP 組み込みの +auto-reconnect で回復できず異常終了した場合に、最大
    RETRY_MAX 回・RETRY_INTERVAL 秒間隔で再起動する(Windows 版の RdpSessionView と
    同じ方針)。ユーザー起因の終了(USER_EXIT_CODES、ウィンドウを閉じた場合の
    131+中断ログ、「切断」ボタン経由)ではリトライしない。
    """

    def __init__(self, profile: dict, xfreerdp: str):
        self.profile = profile
        self.xfreerdp = xfreerdp
        self.state = "接続中"
        self.alive = True
        self._proc: subprocess.Popen | None = None
        self._user_stop = False
        self._log_offset = 0  # この接続の sdl-freerdp 出力が app.log のどこから始まるか
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._user_stop = True
        proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()

    def _spawn(self) -> subprocess.Popen:
        password = keychain_get_password(self.profile["id"])
        rdp_args = build_rdp_args(self.profile)
        if password is not None:
            # /from-stdin は SDL クライアントだと GUI ダイアログになりパイプから
            # 受け取れないため、/args-from:stdin で「全引数を stdin から」渡す
            # (1 行 = 1 引数)。これなら平文パスワードが ps に出ない。
            argv = [self.xfreerdp, "/args-from:stdin"]
            payload = "\n".join(rdp_args + [f"/p:{password}"]) + "\n"
        else:
            # パスワード未登録時は SDL クライアントの認証ダイアログに任せる
            argv = [self.xfreerdp] + rdp_args
            payload = None
        log(f"接続開始: {display_text(self.profile)} → {self.profile['host']}:{self.profile['port']}")
        # どのオプションで接続したかをログから確定できるようにする。パスワードは
        # /args-from:stdin 経由で rdp_args には含まれないため平文は残らない。
        log(f"  引数: {' '.join(rdp_args)}")
        self._log_offset = os.path.getsize(LOG_PATH)  # ユーザー中断判定用(_user_aborted_in_log)
        logf = open(LOG_PATH, "a", encoding="utf-8")
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE if payload is not None else subprocess.DEVNULL,
            stdout=logf, stderr=logf, text=True)
        logf.close()  # 子プロセス側に fd が複製済みなので親側は閉じてよい
        if payload is not None:
            try:
                proc.stdin.write(payload)
                proc.stdin.flush()
                proc.stdin.close()
            except BrokenPipeError:
                pass  # 起動即失敗時。終了コード側で拾う
        return proc

    def _window_script(self, body: str) -> str:
        """このセッションのウィンドウ(タイトルで特定)を操作する AppleScript を組み立てる。"""
        title = display_text(self.profile).replace("\\", "\\\\").replace('"', '\\"')
        return (
            'tell application "System Events" to tell '
            '(first process whose name contains "sdl-freerdp")\n'
            f'  set win to first window whose name contains "{title}"\n'
            f'{body}\n'
            'end tell'
        )

    def _maximize_window(self) -> None:
        # SDL は Retina では「解像度 ÷ ピクセル密度」のポイント数でしかウィンドウを
        # 作れず(/smart-sizing:WxH のウィンドウ指定も無視される)、4K だと半分の
        # 大きさで開いてしまう。接続後に AppleScript でほぼ全画面まで広げる
        # (/smart-sizing 有効なので中身も追従して拡大される)。
        w, h = SCREEN_SIZE
        script = self._window_script(
            '  set position of win to {0, 25}\n'
            f'  set size of win to {{{w}, {h - 25}}}'
        )
        for _ in range(20):  # ウィンドウが出るまで最大 10 秒待つ
            if self._proc is None or self._proc.poll() is not None:
                return
            r = subprocess.run(["osascript", "-e", script], capture_output=True)
            if r.returncode == 0:
                return
            time.sleep(0.5)
        log(f"ウィンドウの拡大に失敗(権限未許可の可能性): {display_text(self.profile)}")

    def toggle_fullscreen(self) -> None:
        """セッションウィンドウの macOS ネイティブ全画面を切り替える(Windows 版の F11 相当)。

        FreeRDP の +f はキーボードが全部リモートへ送られ脱出不能になるため使わず、
        AppleScript で AXFullScreen を反転する。ネイティブ全画面はマウスを画面上端へ
        寄せればメニューバー(緑ボタン)が出るので、ランチャーのボタン以外でも解除できる
        (Windows 版の上端接続バーに相当する脱出手段)。
        """
        threading.Thread(target=self._toggle_fullscreen, daemon=True).start()

    def _toggle_fullscreen(self) -> None:
        script = self._window_script(
            '  set value of attribute "AXFullScreen" of win to '
            'not (value of attribute "AXFullScreen" of win)'
        )
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        if r.returncode != 0:
            log(f"全画面切り替えに失敗: {r.stderr.strip() or f'rc={r.returncode}'}")

    def _user_aborted_in_log(self) -> bool:
        """この接続の sdl-freerdp 出力に「ユーザーによる中断」の痕跡があるか。

        ウィンドウを閉じても exit code はネットワーク断と同じ 131 (CONN_FAILED) に
        なるため、区別はログ出力にしか現れない。app.log のこの接続以降の断片から
        中断マーカーを探す(複数セッション同時接続時は他セッションの出力が混ざり
        得るが、単一利用が前提の道具なので許容)。
        """
        try:
            with open(LOG_PATH, encoding="utf-8", errors="replace") as f:
                f.seek(self._log_offset)
                tail = f.read()
        except OSError:
            return False
        return ("Connection aborted by user" in tail
                or "ERRCONNECT_CONNECT_CANCELLED" in tail)

    def _run(self) -> None:
        retries = 0
        while True:
            started = time.monotonic()
            try:
                self._proc = self._spawn()
            except OSError as e:
                log(f"xfreerdp の起動に失敗: {e}")
                self.state = "起動失敗"
                break
            self.state = "接続中"
            self._maximize_window()
            rc = self._proc.wait()
            uptime = time.monotonic() - started
            log(f"切断: {display_text(self.profile)} (exit={rc}, uptime={uptime:.0f}s)")
            if (self._user_stop or rc in USER_EXIT_CODES
                    or (rc == EXIT_CONN_FAILED and self._user_aborted_in_log())):
                self.state = "切断"
                break
            if uptime >= STABLE_UPTIME:
                retries = 0
            retries += 1
            if retries > RETRY_MAX:
                self.state = "再接続失敗"
                log(f"再接続を諦めました: {display_text(self.profile)} ({RETRY_MAX} 回失敗)")
                break
            self.state = f"再接続中 ({retries}/{RETRY_MAX})"
            log(f"再接続 {retries}/{RETRY_MAX}: {display_text(self.profile)}")
            time.sleep(RETRY_INTERVAL)
        self.alive = False


# ---------------------------------------------------------------- 編集ダイアログ

class ProfileDialog(tk.Toplevel):
    """プロファイルの追加・編集。パスワード欄が空欄のときは既存値を維持する(Windows 版と同じ規約)。"""

    def __init__(self, parent: tk.Tk, profile: dict, is_new: bool):
        super().__init__(parent)
        self.title("プロファイルの追加" if is_new else "プロファイルの編集")
        self.resizable(False, False)
        self.transient(parent)
        self.result: dict | None = None
        self.password: str | None = None  # None = 変更なし
        self._profile = profile

        body = ttk.Frame(self, padding=12)
        body.grid(sticky="nsew")

        self._vars = {
            "name": tk.StringVar(value=profile["name"]),
            "host": tk.StringVar(value=profile["host"]),
            "port": tk.StringVar(value=str(profile["port"])),
            "username": tk.StringVar(value=profile["username"]),
            "domain": tk.StringVar(value=profile["domain"]),
            "password": tk.StringVar(),
            "redirect_clipboard": tk.BooleanVar(value=profile["redirect_clipboard"]),
            "redirect_drives": tk.BooleanVar(value=profile["redirect_drives"]),
            "use_nla": tk.BooleanVar(value=profile["use_nla"]),
        }

        rows = [
            ("表示名", "name", ""),
            ("ホスト", "host", ""),
            ("ポート", "port", ""),
            ("ユーザー名", "username", ""),
            ("ドメイン", "domain", "(通常は空欄)"),
            ("パスワード", "password", "" if is_new else "(空欄で変更なし)"),
        ]
        for i, (label, key, hint) in enumerate(rows):
            ttk.Label(body, text=label).grid(row=i, column=0, sticky="e", padx=(0, 8), pady=2)
            show = "*" if key == "password" else ""
            ttk.Entry(body, textvariable=self._vars[key], width=32, show=show)\
                .grid(row=i, column=1, sticky="we", pady=2)
            if hint:
                ttk.Label(body, text=hint, foreground="gray").grid(row=i, column=2, sticky="w", padx=(6, 0))

        checks = [
            ("クリップボードを共有する", "redirect_clipboard"),
            ("ローカルドライブを共有する", "redirect_drives"),
            ("NLA を強制する(通常はオフ = 自動交渉)", "use_nla"),
        ]
        for j, (label, key) in enumerate(checks):
            ttk.Checkbutton(body, text=label, variable=self._vars[key])\
                .grid(row=len(rows) + j, column=1, columnspan=2, sticky="w", pady=2)

        buttons = ttk.Frame(body)
        buttons.grid(row=len(rows) + len(checks), column=1, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="キャンセル", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="OK", command=self._on_ok).pack(side="right", padx=(0, 8))

        self.bind("<Return>", lambda _e: self._on_ok())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()
        body.winfo_toplevel().update_idletasks()
        self.wait_window()

    def _on_ok(self) -> None:
        host = self._vars["host"].get().strip()
        username = self._vars["username"].get().strip()
        if not host or not username:
            messagebox.showwarning("入力不足", "ホストとユーザー名は必須です。", parent=self)
            return
        try:
            port = int(self._vars["port"].get().strip() or "3389")
        except ValueError:
            messagebox.showwarning("入力不足", "ポートは数値で入力してください。", parent=self)
            return
        self.result = {
            **self._profile,
            "name": self._vars["name"].get().strip(),
            "host": host,
            "port": port,
            "username": username,
            "domain": self._vars["domain"].get().strip(),
            "redirect_clipboard": self._vars["redirect_clipboard"].get(),
            "redirect_drives": self._vars["redirect_drives"].get(),
            "use_nla": self._vars["use_nla"].get(),
        }
        entered = self._vars["password"].get()
        if entered:
            self.password = entered
        self.destroy()


# ---------------------------------------------------------------- メインウィンドウ

class MainWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Ubuntu Remote")
        self.root.geometry("560x320")
        self.profiles = load_profiles()
        self.sessions: dict[str, Session] = {}  # profile id → Session
        self.xfreerdp = find_xfreerdp()

        toolbar = ttk.Frame(root, padding=(8, 8, 8, 0))
        toolbar.pack(fill="x")
        for label, command in [
            ("接続", self.connect), ("切断", self.disconnect), ("全画面", self.toggle_fullscreen),
            ("追加", self.add_profile), ("編集", self.edit_profile), ("削除", self.delete_profile),
        ]:
            ttk.Button(toolbar, text=label, command=command).pack(side="left", padx=(0, 6))
        # Windows 版と同じく F11 でも切り替え(ランチャーにフォーカスがあるときのみ届く)
        root.bind("<F11>", lambda _e: self.toggle_fullscreen())

        self.tree = ttk.Treeview(root, columns=("target", "state"), show="tree headings")
        self.tree.heading("#0", text="表示名")
        self.tree.heading("target", text="接続先")
        self.tree.heading("state", text="状態")
        self.tree.column("#0", width=180)
        self.tree.column("target", width=220)
        self.tree.column("state", width=120)
        self.tree.pack(fill="both", expand=True, padx=8, pady=8)
        self.tree.bind("<Double-1>", lambda _e: self.connect())

        self.refresh_tree()
        self.root.after(500, self._poll_sessions)

        if not self.xfreerdp:
            messagebox.showwarning(
                "FreeRDP が見つかりません",
                "xfreerdp が見つかりません。接続には FreeRDP が必要です。\n\n"
                "  brew install freerdp\n\n"
                "プロファイルの管理だけならこのまま使えます。")

    # ---- 表示

    def refresh_tree(self) -> None:
        selected = self.selected_id()
        self.tree.delete(*self.tree.get_children())
        for p in self.profiles:
            session = self.sessions.get(p["id"])
            state = session.state if session else ""
            self.tree.insert("", "end", iid=p["id"], text=display_text(p),
                             values=(f"{p['username']}@{p['host']}:{p['port']}", state))
        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected)

    def _poll_sessions(self) -> None:
        for pid, session in list(self.sessions.items()):
            if not session.alive:
                del self.sessions[pid]
            if self.tree.exists(pid):
                self.tree.set(pid, "state", session.state)
        self.root.after(500, self._poll_sessions)

    def selected_id(self) -> str | None:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def selected_profile(self) -> dict | None:
        pid = self.selected_id()
        if not pid:
            messagebox.showinfo("選択なし", "プロファイルを選択してください。")
            return None
        return next((p for p in self.profiles if p["id"] == pid), None)

    # ---- 操作

    def connect(self) -> None:
        profile = self.selected_profile()
        if not profile:
            return
        if not self.xfreerdp:
            messagebox.showwarning("FreeRDP が見つかりません",
                                   "brew install freerdp を実行してください。")
            return
        existing = self.sessions.get(profile["id"])
        if existing and existing.alive:
            messagebox.showinfo("接続済み", f"{display_text(profile)} は既に接続中です。")
            return
        self.sessions[profile["id"]] = Session(profile, self.xfreerdp)
        self.refresh_tree()

    def disconnect(self) -> None:
        profile = self.selected_profile()
        if not profile:
            return
        session = self.sessions.get(profile["id"])
        if session and session.alive:
            session.stop()

    def toggle_fullscreen(self) -> None:
        profile = self.selected_profile()
        if not profile:
            return
        session = self.sessions.get(profile["id"])
        if not session or not session.alive:
            messagebox.showinfo("未接続", f"{display_text(profile)} は接続していません。")
            return
        session.toggle_fullscreen()

    def add_profile(self) -> None:
        dialog = ProfileDialog(self.root, default_profile(), is_new=True)
        if not dialog.result:
            return
        self.profiles.append(dialog.result)
        save_profiles(self.profiles)
        if dialog.password is not None:
            keychain_set_password(dialog.result["id"], dialog.password)
        self.refresh_tree()

    def edit_profile(self) -> None:
        profile = self.selected_profile()
        if not profile:
            return
        dialog = ProfileDialog(self.root, profile, is_new=False)
        if not dialog.result:
            return
        self.profiles = [dialog.result if p["id"] == profile["id"] else p for p in self.profiles]
        save_profiles(self.profiles)
        if dialog.password is not None:  # 空欄 = 既存パスワード維持
            keychain_set_password(profile["id"], dialog.password)
        self.refresh_tree()

    def delete_profile(self) -> None:
        profile = self.selected_profile()
        if not profile:
            return
        if not messagebox.askyesno("削除の確認",
                                   f"{display_text(profile)} を削除しますか?\n(Keychain のパスワードも削除されます)"):
            return
        session = self.sessions.pop(profile["id"], None)
        if session and session.alive:
            session.stop()
        self.profiles = [p for p in self.profiles if p["id"] != profile["id"]]
        save_profiles(self.profiles)
        keychain_delete_password(profile["id"])
        self.refresh_tree()


def main() -> None:
    global SCREEN_SIZE
    os.makedirs(SUPPORT_DIR, exist_ok=True)
    log("起動")
    root = tk.Tk()
    SCREEN_SIZE = (root.winfo_screenwidth(), root.winfo_screenheight())
    MainWindow(root)
    # ランチャーを閉じても接続中の xfreerdp ウィンドウは残る(自動再接続の監視だけ止まる)
    root.mainloop()
    log("終了")


if __name__ == "__main__":
    main()
