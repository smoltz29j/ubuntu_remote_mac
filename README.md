# Ubuntu Remote Mac

日本語 | [English](#ubuntu-remote-mac-english)

Ubuntu マシン(xrdp)へ接続するための macOS 用リモートデスクトップクライアントです。

Windows 版 [ubuntu_remote](https://github.com/smoltz29j/ubuntu_remote) の姉妹プロジェクト。macOS には Windows の RDP ActiveX のような「自ウィンドウに埋め込める RDP コントロール」が無いため、tkinter のプロファイル管理 UI から FreeRDP(`sdl-freerdp`)を子プロセスとして起動する軽量ランチャー構成をとっています(Python 単一ファイル・標準ライブラリのみ)。

## 機能

- **接続プロファイル管理** — 複数の接続先を一覧に登録し、ダブルクリックで接続。パスワードは macOS Keychain に保存(JSON やログに平文を残さない)
- **自動ログイン** — 接続情報を `/args-from:stdin` で FreeRDP に渡し、xrdp のログイン画面を自動突破(平文パスワードが `ps` に一瞬も出ない)
- **自動再接続** — FreeRDP 組み込みの再接続に加え、ランチャー側でも非ユーザー起因の異常終了を最大 5 回、3 秒間隔でリトライ。ウィンドウを閉じた・リモートでログアウトした等のユーザー起因の終了ではリトライしない
- **全画面表示** — 「全画面」ボタンまたは F11 で macOS ネイティブ全画面を切替。解除はもう一度押すか、マウスを画面上端に寄せてメニューバーの緑ボタンから
- **ウィンドウの自動最大化** — SDL クライアントが Retina で半分サイズに開いてしまう問題を、接続直後に AppleScript で画面いっぱいまで補正(`/smart-sizing` で中身も追従)
- **音声リダイレクト** — サーバー側に `pipewire-module-xrdp` があればクライアントで再生
- **クリップボード / ドライブ共有** — プロファイルごとに有効・無効を設定可能
- **NLA** — 既定はプロトコル自動交渉。プロファイルごとに NLA 強制も可能
- **複数同時接続** — セッションごとに独立した sdl-freerdp ウィンドウ。ランチャーを閉じても接続中のセッションはそのまま残る

## xrdp 向けの最適化

- **`+rfx -nsc` で RemoteFX を要求** — 既定で選ばれる NSCodec は ARM Mac の Homebrew ビルドでは NEON 最適化が未実装で描画が著しく遅いため無効化。GFX 非対応の xrdp 0.9 系では RemoteFX が実質最速
- 接続種別 LAN を明示(`/network:lan`)
- 自己署名証明書前提のため**サーバー証明書検証をスキップ**(`/cert:ignore`)、NLA は既定で強制しない(自動交渉)

## 動作環境

- macOS(動作確認は Apple Silicon)
- FreeRDP(`sdl-freerdp`): `brew install freerdp`
- Tk 8.6 以上を持つ Python 3: `brew install python python-tk`
  (システムの `/usr/bin/python3` は Tk 8.5 のためウィンドウが真っ黒に描画され使えない。`run.sh` が適切な python3 を自動で選ぶ)
- ウィンドウの自動最大化・全画面切替に System Events(AppleScript)を使うため、初回実行時に**アクセシビリティ(オートメーション)権限の許可**が必要

## インストール・実行

```bash
brew install freerdp python python-tk
./run.sh                                    # Tk 8.6+ の python3 を探して起動
```

```bash
python3 -m py_compile ubuntu_remote.py      # 構文チェック(テストは置かない方針。動作確認は実機接続)
```

## 使い方

1. 「追加」で接続先を登録(表示名・ホスト・ポート・ユーザー名・パスワードなど)
2. 一覧のダブルクリックまたは「接続」ボタンで接続
3. 「全画面」ボタンか F11 で全画面切替(選択中のセッションが対象)

パスワードを登録しなかった場合は、接続時に FreeRDP の認証ダイアログが開きます。編集ダイアログでパスワード欄を空欄のまま保存すると既存のパスワードを維持します。

### xrdp サーバー側のメモ

- GNOME リモートログイン(gnome-remote-desktop)が 3389 を使っている場合、xrdp を別ポート(例: 3390)で動かして接続先をそちらに向けること。GNOME 側は NLA 必須・認証情報も別物のため、誤って繋ぐと認証エラーになる
- 音声を鳴らすには `pipewire-module-xrdp` を導入しておく

## 設定ファイル・ログ

| パス | 内容 |
|---|---|
| `~/Library/Application Support/UbuntuRemote/profiles.json` | 接続プロファイル(パスワードは含まない) |
| macOS Keychain(service=`UbuntuRemote`) | パスワード |
| `~/Library/Application Support/UbuntuRemote/app.log` | ランチャーのログ + sdl-freerdp の出力 |

## 技術スタック

- Python 3 / tkinter(標準ライブラリのみ、単一ファイル)
- [FreeRDP](https://www.freerdp.com/)(`sdl-freerdp`)を子プロセスとして起動

---

# Ubuntu Remote Mac (English)

[日本語](#ubuntu-remote-mac) | English

A macOS remote desktop client for connecting to Ubuntu machines running xrdp.

This is the sibling project of [ubuntu_remote](https://github.com/smoltz29j/ubuntu_remote) for Windows. Since macOS has no embeddable RDP control equivalent to the Windows RDP ActiveX, this project takes a lightweight launcher approach: a tkinter profile-management UI that spawns FreeRDP (`sdl-freerdp`) as a child process (a single Python file, standard library only).

## Features

- **Connection profile management** — Register multiple hosts in a list and connect with a double-click. Passwords are stored in the macOS Keychain (never in plain text in JSON or logs)
- **Auto login** — Credentials are passed to FreeRDP via `/args-from:stdin`, automatically passing the xrdp login screen (the plaintext password never appears in `ps`)
- **Auto reconnect** — In addition to FreeRDP's built-in reconnection, the launcher retries abnormal exits up to 5 times at 3-second intervals. User-initiated exits (closing the window, logging out on the remote, etc.) are not retried
- **Full screen** — Toggle native macOS full screen with the "全画面" (Full Screen) button or F11. Exit by pressing it again, or move the mouse to the top edge and use the green button in the menu bar
- **Automatic window maximization** — Works around the SDL client opening at half size on Retina displays by resizing the window to fill the screen via AppleScript right after connecting (contents follow thanks to `/smart-sizing`)
- **Audio redirection** — Plays sound on the client if the server has `pipewire-module-xrdp` installed
- **Clipboard / drive sharing** — Can be enabled or disabled per profile
- **NLA** — Protocol negotiation by default; NLA can be forced per profile
- **Multiple simultaneous sessions** — Each session is an independent sdl-freerdp window. Closing the launcher leaves connected sessions running

## Optimizations for xrdp

- **Requests RemoteFX with `+rfx -nsc`** — The NSCodec chosen by default has no NEON optimization in the Homebrew build on ARM Macs and renders very slowly, so it is disabled. On GFX-less xrdp 0.9, RemoteFX is effectively the fastest codec
- Explicitly sets connection type LAN (`/network:lan`)
- **Skips server certificate validation** (`/cert:ignore`) since xrdp uses self-signed certificates; NLA is not forced by default (auto negotiation)

## Requirements

- macOS (verified on Apple Silicon)
- FreeRDP (`sdl-freerdp`): `brew install freerdp`
- Python 3 with Tk 8.6+: `brew install python python-tk`
  (The system `/usr/bin/python3` ships Tk 8.5, which renders a black window on recent macOS. `run.sh` picks a suitable python3 automatically)
- Window maximization and full-screen toggling use System Events (AppleScript), so **Accessibility (Automation) permission** must be granted on first run

## Install & Run

```bash
brew install freerdp python python-tk
./run.sh                                    # finds a python3 with Tk 8.6+ and launches
```

```bash
python3 -m py_compile ubuntu_remote.py      # syntax check (no test suite by design; verification is done against a real server)
```

## Usage

1. Click "追加" (Add) to register a host (display name, host, port, username, password, etc.)
2. Double-click an entry in the list or click "接続" (Connect) to connect
3. Toggle full screen with the "全画面" (Full Screen) button or F11 (applies to the selected session)

If no password is registered, FreeRDP shows its authentication dialog on connect. Leaving the password field empty in the edit dialog keeps the existing password.

### Notes on the xrdp server side

- If GNOME Remote Login (gnome-remote-desktop) is using port 3389, run xrdp on a different port (e.g. 3390) and point the profile there. The GNOME side requires NLA with separate credentials, so connecting to it by mistake results in an authentication error
- To get audio, install `pipewire-module-xrdp` on the server

## Config files and logs

| Path | Contents |
|---|---|
| `~/Library/Application Support/UbuntuRemote/profiles.json` | Connection profiles (passwords not included) |
| macOS Keychain (service=`UbuntuRemote`) | Passwords |
| `~/Library/Application Support/UbuntuRemote/app.log` | Launcher log + sdl-freerdp output |

## Tech stack

- Python 3 / tkinter (standard library only, single file)
- [FreeRDP](https://www.freerdp.com/) (`sdl-freerdp`) spawned as a child process
