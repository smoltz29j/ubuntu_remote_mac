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
LOG_MAX_BYTES = 5 * 1024 * 1024  # 起動時にこれを超えていたら app.log.1 へ退避(1 世代)

# sdl-freerdp のユーザー起因の exit code(SDL クライアント自身もエラー表示しない集合)。
# 0=正常終了, 1=DISCONNECT, 2=LOGOFF(リモートでログアウト), 11=DISCONNECT_BY_USER,
# 145=CONNECT_CANCELLED。これらはリトライしない。
# 注意: ウィンドウを閉じたときの実際の exit は 131 (CONN_FAILED) で、ネットワーク断で
# 内蔵再接続に失敗したときと同じ汎用値(FreeRDP 3.27 のソースとログで確認)。
# 131 はログの中断マーカーで区別する(Session._user_aborted_in_log)。
USER_EXIT_CODES = {0, 1, 2, 11, 145}
EXIT_LOGOFF = 2        # 別 PC に蹴られたときもこれ(ERRINFO_LOGOFF_BY_USER)。Session._detect_kicker
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
    if not isinstance(raw, list) or not all(isinstance(p, dict) for p in raw):
        # 手編集で壊れた JSON(トップレベルが配列でない等)で起動時に落ちないようにする
        log("profiles.json の形式が不正(プロファイルの配列ではない)のため無視します")
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
            try:
                return bytes.fromhex(m.group(1)).decode("utf-8")
            except UnicodeDecodeError:
                log(f"Keychain のパスワードが UTF-8 として復号できません: {profile_id}")
                return None
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


def password_problem(password: str) -> str | None:
    """保存・受け渡しできないパスワードなら理由を返す(None = 問題なし)。

    - 改行: /args-from:stdin は 1 行 = 1 引数なので渡せない
    - タブなどの制御文字: `security -g` は空白類を含むパスワードを hex ではなく
      引用形式で出し、制御文字を `\\011` のような 8 進エスケープにするため、
      リテラルのバックスラッシュと区別できず往復が保証できない
    ProfileDialog と tools/register_password.py の両方で使う。
    """
    if any(ord(c) < 0x20 or c == "\x7f" for c in password):
        return "改行やタブなどの制御文字を含むパスワードは扱えません。"
    return None


# ---------------------------------------------------------------- 接続前チェック

def _local_ipv4s() -> set[str]:
    r = subprocess.run(["ifconfig"], capture_output=True, text=True)
    return set(re.findall(r"\binet (\d+\.\d+\.\d+\.\d+)", r.stdout))


def other_rdp_clients(host: str, port: int) -> list[str] | None:
    """接続先の RDP ポートに確立済み接続を持つ「他の PC」の IP 一覧を返す。

    xrdp は同一セッションへ新しい接続が来ると古い接続を蹴る(CLAUDE.md
    「接続がすぐ切れるとき」参照。2026-08-08 に別マシンとの蹴り合いを実測)ため、
    先客がいるときはこちらから接続しない、の判定に使う。接続先で ss を実行する
    必要があるので ssh(鍵認証)経由。この Mac 自身の接続(= 全ローカル IP)は
    先客に数えない。ssh が通らない・ss が無いなど確認できない場合は None を返す
    (= 判定不能。ガードは best-effort とし、従来どおり接続する)。
    """
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host,
             f"ss -Htn state established '( sport = :{port} )'"],
            capture_output=True, text=True, timeout=12)
    except (subprocess.TimeoutExpired, OSError) as e:
        log(f"先客チェック不能(ガードなしで接続): {host}: {e}")
        return None
    if r.returncode != 0:
        # 判定できなかったこと自体をログに残す。残さないと、後で蹴られたときに
        # 「ガードが効いていたのか」をログから判断できない
        detail = r.stderr.strip().splitlines()[-1:] or [f"rc={r.returncode}"]
        log(f"先客チェック不能(ガードなしで接続): {host}: {detail[0]}")
        return None
    try:
        local = _local_ipv4s()
    except OSError as e:
        # ローカル IP が取れないと自分の接続を先客と誤認して接続を止めてしまうので判定不能扱い
        log(f"先客チェック不能(ガードなしで接続): ローカル IP を取得できません: {e}")
        return None
    peers: list[str] = []
    for line in r.stdout.splitlines():
        parts = line.split()  # Recv-Q Send-Q Local:Port Peer:Port
        if len(parts) < 4:
            continue
        ip = parts[3].rsplit(":", 1)[0].strip("[]")
        if ip.startswith("::ffff:"):  # IPv4-mapped IPv6 表記
            ip = ip[len("::ffff:"):]
        if ip not in local and ip not in peers:
            peers.append(ip)
    return peers


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
        # 日本語配列を明示する。なお IME の切り替えは かな/英数 キーでは不可
        # (FreeRDP 3.30 以前の SDL クライアントが捨てる。3.31.1 で対応、remap 案は
        # CLAUDE.md「かな/英数 を通す計画」)。現状は Ctrl+Shift+; を直接押す運用
        # (Karabiner は 2026-09-03 に撤去)。詳細は CLAUDE.md「日本語入力」参照。
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
    接続前(初回・再接続とも)に other_rdp_clients で先客(別 PC)を確認し、
    いれば接続しない(相手を蹴って奪い合いになるのを防ぐ)。
    """

    def __init__(self, profile: dict, xfreerdp: str):
        self.profile = profile
        self.xfreerdp = xfreerdp
        self.state = "接続中"
        self.alive = True
        self.blocked_by: str | None = None  # 接続を中止させた先客の IP(UI 通知用)
        self.kicked_by: str | None = None   # 接続後にこちらを蹴った別 PC の IP(UI 通知用)
        self._has_password = False          # False なら SDL の認証ダイアログを待つ
        self._proc: subprocess.Popen | None = None
        self._stop_event = threading.Event()  # set = ユーザーによる「切断」
        self._log_offset = 0  # この接続の sdl-freerdp 出力が app.log のどこから始まるか
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()  # リトライ間隔の待機中でも即座に中断できる
        proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()

    def _spawn(self) -> subprocess.Popen:
        password = keychain_get_password(self.profile["id"])
        self._has_password = password is not None
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
        self._log_offset = os.path.getsize(LOG_PATH)  # 切断理由の判定用(_log_tail)
        # 子プロセス側に fd が複製されるので、Popen 後は親側のハンドルを閉じてよい
        # (with にしておけば Popen が OSError で失敗したときも閉じ漏れない)
        with open(LOG_PATH, "a", encoding="utf-8") as logf:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE if payload is not None else subprocess.DEVNULL,
                stdout=logf, stderr=logf, text=True)
        if payload is not None:
            try:
                proc.stdin.write(payload)
                proc.stdin.flush()
            except BrokenPipeError:
                pass  # 起動即失敗時。終了コード側で拾う
            finally:
                # flush で失敗しても必ず閉じる(閉じ漏れると親側のパイプ fd が残り、
                # GC 時の再 flush で "Exception ignored" が stderr に出る)
                try:
                    proc.stdin.close()
                except BrokenPipeError:
                    pass
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
        # パスワード未登録時は SDL の認証ダイアログにユーザーが入力し終わるまで
        # セッションウィンドウが出ないので、待ち時間を長く取る
        deadline = time.monotonic() + (10 if self._has_password else 120)
        while time.monotonic() < deadline:
            if self._proc is None or self._proc.poll() is not None:
                return
            r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
            if r.returncode == 0:
                return
            # -1743 = オートメーション(System Events への Apple Event 送信)未許可、
            # -25211 = アクセシビリティ未許可。どちらも待っても解決しないので即座に諦め、
            # ウィンドウ未出現(-1719)と区別して原因をログに残す
            if "(-1743)" in r.stderr or "(-25211)" in r.stderr:
                log("ウィンドウの拡大に失敗: システム設定 > プライバシーとセキュリティ で "
                    f"Python にオートメーション/アクセシビリティを許可してください: {r.stderr.strip()}")
                return
            time.sleep(0.5)
        log(f"ウィンドウの拡大に失敗(ウィンドウが時間内に出なかった): {display_text(self.profile)}")

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

    def _log_tail(self) -> str:
        """この接続の sdl-freerdp 出力(app.log のこの接続以降の断片)。

        切断理由の判別に使う。マーカーは切断時に出る = 末尾付近にあるので、
        長時間セッションでログが肥大していても末尾 1 MiB だけ読めば足りる。
        複数セッション同時接続時は他セッションの出力が混ざり得るが、
        単一利用が前提の道具なので許容。
        """
        try:
            with open(LOG_PATH, "rb") as f:
                size = f.seek(0, os.SEEK_END)
                f.seek(max(self._log_offset, size - 1024 * 1024))
                return f.read().decode("utf-8", errors="replace")
        except OSError:
            return ""

    def _user_aborted_in_log(self) -> bool:
        """ユーザーによる中断の痕跡があるか。

        ウィンドウを閉じても exit code はネットワーク断と同じ 131 (CONN_FAILED) に
        なるため、区別はログ出力にしか現れない。
        """
        tail = self._log_tail()
        return ("Connection aborted by user" in tail
                or "ERRCONNECT_CONNECT_CANCELLED" in tail)

    def _detect_kicker(self) -> None:
        """exit=2 のとき、別 PC に蹴られたのかを判定して kicked_by に入れる。

        xrdp は同一セッションへ新しい接続が来ると古い接続を蹴り、蹴られた側には
        ERRINFO_LOGOFF_BY_USER (exit=2) が返る。リモートで自分がログアウトした場合と
        exit code では区別できないので、切断直後に接続先の確立済み接続を見て
        別 PC がいればそれを蹴った相手とみなす(2026-08-08 の Baldwin の件の再発検知)。
        """
        if "ERRINFO_LOGOFF_BY_USER" not in self._log_tail():
            return
        others = other_rdp_clients(self.profile["host"], self.profile["port"])
        if others:
            self.kicked_by = ", ".join(others)
            log(f"別の PC に蹴られた可能性: {display_text(self.profile)} ({self.kicked_by})")

    def _run(self) -> None:
        # 監視スレッドが予期しない例外で黙って死ぬと alive が True のまま残り、UI 上は
        # 永遠に「接続中」でそのプロファイルに再接続できなくなる。必ず終了状態にする
        # (sdl-freerdp 自体は殺さない — ランチャー側の都合でセッションを落とさない方針)。
        try:
            self._run_loop()
        except Exception as e:
            log(f"セッション監視で予期しないエラー: {display_text(self.profile)}: {e!r}")
            self.state = "監視エラー"
        finally:
            self.alive = False

    def _run_loop(self) -> None:
        retries = 0
        while True:
            # 先客チェック: 別の PC が接続中なら、こちらが接続すると相手を蹴って
            # 奪い合いになるだけなので中止する(初回・自動再接続とも)。
            self.state = "先客確認中"  # ssh が遅いと数秒かかるので「接続中」と区別する
            others = other_rdp_clients(self.profile["host"], self.profile["port"])
            if self._stop_event.is_set():  # チェック中(ssh 最大数秒)の「切断」
                self.state = "切断"
                break
            if others:
                self.blocked_by = ", ".join(others)
                self.state = "先客あり"
                log(f"接続中止: {display_text(self.profile)} には別の PC が接続中 ({self.blocked_by})")
                break
            started = time.monotonic()
            try:
                self._proc = self._spawn()
            except OSError as e:
                log(f"xfreerdp の起動に失敗: {e}")
                self.state = "起動失敗"
                break
            if self._stop_event.is_set():  # _spawn 中に「切断」された場合の取りこぼし防止
                self._proc.terminate()
            self.state = "接続中"
            self._maximize_window()
            rc = self._proc.wait()
            uptime = time.monotonic() - started
            log(f"切断: {display_text(self.profile)} (exit={rc}, uptime={uptime:.0f}s)")
            if rc == EXIT_LOGOFF and not self._stop_event.is_set():
                self._detect_kicker()
            if (self._stop_event.is_set() or rc in USER_EXIT_CODES
                    or (rc == EXIT_CONN_FAILED and self._user_aborted_in_log())):
                self.state = "蹴られた" if self.kicked_by else "切断"
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
            if self._stop_event.wait(RETRY_INTERVAL):  # 待機中の「切断」で即終了
                self.state = "切断"
                break


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
            entry = ttk.Entry(body, textvariable=self._vars[key], width=32, show=show)
            entry.grid(row=i, column=1, sticky="we", pady=2)
            if i == 0:
                entry.focus_set()  # 開いた直後から入力できるようにする
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
            if not 1 <= port <= 65535:
                raise ValueError(port)
        except ValueError:
            messagebox.showwarning("入力不足", "ポートは 1〜65535 の数値で入力してください。", parent=self)
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
            problem = password_problem(entered)
            if problem:
                messagebox.showwarning("使用できないパスワード", problem, parent=self)
                return
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
        self.tree.bind("<Double-1>", self._on_double_click)

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
            if not session.alive and session.blocked_by:
                blocked, session.blocked_by = session.blocked_by, None
                messagebox.showwarning(
                    "先客あり",
                    f"{display_text(session.profile)} には別の PC ({blocked}) が接続中のため、"
                    "接続を中止しました。\n"
                    "接続すると相手を切断してしまいます(xrdp は同一セッションの新しい接続が"
                    "古い接続を蹴ります)。\n"
                    "相手側の RDP クライアントを終了してから接続し直してください。")
            if not session.alive and session.kicked_by:
                kicked, session.kicked_by = session.kicked_by, None
                messagebox.showwarning(
                    "別の PC に切断されました",
                    f"{display_text(session.profile)} のセッションに別の PC ({kicked}) が接続し、"
                    "こちらの接続が切断されました。\n"
                    "このまま接続し直すと今度は相手を蹴る奪い合いになるため、自動再接続は"
                    "していません。\n"
                    "相手側の RDP クライアントを終了してから接続し直してください。")
        self.root.after(500, self._poll_sessions)

    def _on_double_click(self, event: tk.Event) -> None:
        # 見出し行や列境界のダブルクリック(列幅調整など)で接続が走らないようにする
        # (#0 列は "tree"、他の列は "cell" と報告される)
        if self.tree.identify_region(event.x, event.y) in ("tree", "cell"):
            self.connect()

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
            self._save_password(dialog.result["id"], dialog.password)
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
            self._save_password(profile["id"], dialog.password)
        self.refresh_tree()

    def _save_password(self, profile_id: str, password: str) -> None:
        # 保存失敗を黙って握りつぶすと「登録したのに接続時にダイアログが出る」ように
        # 見えて原因が分からないため、ここでユーザーに知らせる
        if not keychain_set_password(profile_id, password):
            messagebox.showwarning(
                "パスワード保存に失敗",
                "Keychain へのパスワード保存に失敗しました。\n"
                "接続時は FreeRDP の認証ダイアログで入力してください。\n"
                "(詳細は app.log を参照)", parent=self.root)

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


def rotate_log() -> None:
    # sdl-freerdp の出力も app.log に溜まるため、放っておくと際限なく肥大化する。
    # 起動時(セッションの _log_offset 参照が始まる前)にだけ 1 世代退避する。
    try:
        if os.path.getsize(LOG_PATH) > LOG_MAX_BYTES:
            os.replace(LOG_PATH, LOG_PATH + ".1")
    except OSError:
        pass  # 未作成など。ログが無いだけなので何もしない


def main() -> None:
    global SCREEN_SIZE
    os.makedirs(SUPPORT_DIR, exist_ok=True)
    rotate_log()
    log("起動")
    root = tk.Tk()
    SCREEN_SIZE = (root.winfo_screenwidth(), root.winfo_screenheight())
    MainWindow(root)
    # ランチャーを閉じても接続中の xfreerdp ウィンドウは残る(自動再接続の監視だけ止まる)
    root.mainloop()
    log("終了")


if __name__ == "__main__":
    main()
