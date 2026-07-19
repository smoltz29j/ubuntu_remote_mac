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

xrdp を前提にチューニングしています。0.9 系(Ubuntu 24.04 標準)・0.10 系(GFX/H.264 対応)のどちらでも動作確認済みです(音声リダイレクト含む)。

- **`/gfx:AVC444` で GFX/H.264 を要求** — GFX 対応の xrdp 0.10 系では H.264 がネゴシエートされる(`/gfx` を明示しないとレガシー RemoteFX のままになる)
- **`+rfx -nsc` をフォールバックに指定** — GFX 非対応の xrdp 0.9 系では実質最速の RemoteFX を使う。既定で選ばれる NSCodec は ARM Mac の Homebrew ビルドでは NEON 最適化が未実装で描画が著しく遅いため無効化
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

## 接続先 Ubuntu のセットアップ手順

**2 台(elwhite / glavine)で同じ落とし穴を順番に踏んだので、その全部を手順として残す。**
Ubuntu 24.04 + GNOME で xrdp をソースビルドする前提。apt 版(0.9.x)を使うなら GFX/H.264 が
無い代わりに、下記のうち Xwrapper と PAM はパッケージが面倒を見てくれる。

### 0. どの RDP サーバーに繋ぐか決める

Ubuntu には gnome-remote-desktop が最初から入っていて、**xrdp と紛らわしい**。

| | xrdp | gnome-remote-desktop |
|---|---|---|
| 認証 | Ubuntu のログイン情報 | **専用の資格情報**(GNOME 設定で別途決める) |
| NLA | 不要(`negotiate`) | **必須** |
| セッション | 独立した新規セッション | Remote Login=新規 / Desktop Sharing=**コンソールと同じ画面** |

**このアプリが想定しているのは xrdp。** 誤って gnome-remote-desktop に繋ぐと
`SPNEGO failed 0xc00700ea` などの認証エラーになる。物理画面と同じ画面を共有したいだけなら
xrdp ではなく Desktop Sharing を使うほうが適切(後述の排他制約を回避できる)。

### 1. ポートを決めて空ける

慣例として **xrdp = 3390** に統一している(3389 は gnome-remote-desktop が使いがちなため)。
既に埋まっている場合、gnome-remote-desktop 側を**無効化せずに退避**できる:

```bash
grdctl rdp set-port 3391
grdctl rdp disable-port-negotiation   # 自動で戻らないようにする
systemctl --user restart gnome-remote-desktop
```

### 2. ビルドと導入

```bash
# 依存(libfuse-dev は FUSE 2。libfuse3-dev では configure が通らない)
sudo apt install -y autoconf libtool pkg-config nasm libssl-dev libpam0g-dev \
  libx11-dev libxfixes-dev libxrandr-dev libxml2-dev libjpeg-dev libfuse-dev \
  libmp3lame-dev libopus-dev libfdk-aac-dev libx264-dev libpixman-1-dev \
  xserver-xorg-dev xutils-dev libepoxy-dev libgbm-dev

git clone --depth 1 --branch v0.10.6 --recursive https://github.com/neutrinolabs/xrdp.git
cd xrdp && ./bootstrap
./configure --enable-fuse --enable-pixman --enable-mp3lame --enable-opus \
            --enable-fdkaac --enable-x264
make -j"$(nproc)" && sudo make install     # ← xorgxrdp より先に install する

# xorgxrdp は xrdp の xrdp.pc を要求するので、上を install した後で
git clone --depth 1 --branch v0.10.5 https://github.com/neutrinolabs/xorgxrdp.git
cd xorgxrdp && ./bootstrap
PKG_CONFIG_PATH=/usr/local/lib/pkgconfig ./configure --enable-glamor
make -j"$(nproc)" && sudo make install
```

**注意点:**

- **xorgxrdp を先に configure しようとすると必ず失敗する**(`Package 'xrdp' ... not found`)。
  xrdp を `make install` してからでないと `xrdp.pc` が存在しない
- `--enable-fuse` を落とすと**ドライブリダイレクトとクリップボード経由のファイル転送が消える**
- 設定の格納先は `strict_locations` の既定 (`no`) により **`/etc/xrdp`** になる。
  `--enable-strict-locations` を付けると `/usr/local/etc/xrdp` になる。**マシンごとに違うと混乱する**ので統一するか、どちらか把握しておくこと
- nvenc は上流には無い(NVIDIA 向けの `--enable-nvenc` は fork 独自)。x264 のソフトウェア
  エンコードで十分実用になる

### 3. 設定

#### (A) これを忘れると動かない — 効果を実測で確認済み

```bash
# リモートからの Xorg 起動を許可する。無いと "waitforx: Unable to open display :10"
printf 'allowed_users=anybody\nneeds_root_rights=yes\n' | sudo tee /etc/X11/Xwrapper.config

# Ubuntu セッションモードで起動させる。無いと Dock も壁紙も出ない
cat > ~/.xsessionrc <<'EOS'
export DESKTOP_SESSION=ubuntu
export GNOME_SHELL_SESSION_MODE=ubuntu
export XDG_CURRENT_DESKTOP=ubuntu:GNOME
EOS

sudo systemctl daemon-reload
sudo systemctl enable --now xrdp xrdp-sesman
```

`/etc/xrdp/xrdp.ini` の `port` を決めたポート(例 `3390`)にする。

#### (B) 参考構成に合わせたもの — 個別の必要性は未検証

以下は先行機(elwhite)との差分として一括適用したもので、**それぞれが本当に必要かは
切り分けていない**。害は無いので揃えておいて構わないが、「これが無いと動かない」とは
確認できていない。

| 設定 | 値 |
|---|---|
| `xrdp.ini` の `autorun` | `Xorg`(空だとログイン画面にモジュール選択が出る) |
| `xrdp.ini` の `[Xorg] ip` | `127.0.0.1` |
| `/etc/X11/xrdp/xorg.conf` の `Section "Module"` | `Load "glamoregl"` を追加 |
| グループ | `sudo usermod -aG video,render "$USER"` |

### 4. 音を出す(パッケージだけでは鳴らない)

**`sudo apt install libpipewire-0.3-modules-xrdp` だけでは音は出ない。**
Ubuntu のこのパッケージ (0.2-2) は `.so` を 1 つ入れるだけで、**それをロードする仕組みを
含まない**。上流 [pipewire-module-xrdp](https://github.com/neutrinolabs/pipewire-module-xrdp)
の配布物にある次の 2 ファイルを別途配置する:

| ファイル | 権限 |
|---|---|
| `/usr/libexec/pipewire-module-xrdp/load_pw_modules.sh` | `755 root:root` |
| `/etc/xdg/autostart/pipewire-xrdp.desktop` | `644 root:root` |

上流から直接取得できる(ビルド不要)。`.desktop` は `.in` テンプレートなので
`@pkglibexecdir@` を展開する:

```bash
sudo apt install -y libpipewire-0.3-modules-xrdp

BASE=https://raw.githubusercontent.com/neutrinolabs/pipewire-module-xrdp/v0.2/instfiles
sudo install -d /usr/libexec/pipewire-module-xrdp
curl -fsSL $BASE/load_pw_modules.sh \
  | sudo install -m 755 /dev/stdin /usr/libexec/pipewire-module-xrdp/load_pw_modules.sh
curl -fsSL $BASE/pipewire-xrdp.desktop.in \
  | sed 's#@pkglibexecdir@#/usr/libexec/pipewire-module-xrdp#' \
  | sudo install -m 644 /dev/stdin /etc/xdg/autostart/pipewire-xrdp.desktop
```

`load_pw_modules.sh` の md5 は `2f6f8605d5641306abdf5e7faa324124`(2940 バイト、
`devel` / `v0.2` とも同一。稼働中の elwhite の実物とバイト一致を確認済み)。
既に動いているマシンがあれば `scp` で持ってきてもよい。

動いていればセッション内で
`pw-cli -m -d load-module libpipewire-module-xrdp sink.node.latency=2048 ...` が走っている。

### 5. 日本語入力

Mac の かな/英数 キーは **macOS が IME 層より手前で消費するため RDP には一切流れない**。
Karabiner-Elements で `sdl-freerdp` 前面時のみ別のキーへ変換して送る構成にしている
(詳細は CLAUDE.md)。Ubuntu 側は**接続先ごとに**同じキーバインドを設定しておくこと:

```bash
gsettings set org.gnome.desktop.wm.keybindings switch-input-source \
  "['<Control><Shift>semicolon']"
```

### 6. 運用上の制約

- **同一ユーザーの GNOME セッションは同時に 1 つだけ**(`/run/user/<uid>/bus` がユーザー単位で
  共有されるため)。物理コンソールにログインしたままだと xrdp 側の WM が起動直後に落ちる
  (`Window manager ... exited quickly (0 secs)`)。回避策は次項を参照
- **xrdp は切断済みセッションを保持して再接続時に再アタッチする。**
  そのため `.xsessionrc` や autostart のような**セッション開始時に読まれる設定を変えたら、
  RDP を繋ぎ直すだけでは反映されない**。GNOME のメニューからログアウトすること

### 6-1. 物理画面とリモートを同時に使いたい場合(推奨: リモート専用アカウント)

上の排他制約は**同一ユーザー**の話なので、**リモート用に別アカウントを作れば解決する**。
別ユーザーなら `/run/user/<uid>/bus` が別になり、コンソールとリモートで GNOME セッションを
同時に動かせる。glavine ではこの方式を採っている(コンソール=`smoltz` / リモート=`john`)。

| | 専用アカウント | コンソールをログアウト | Desktop Sharing |
|---|---|---|---|
| 同時利用 | **できる** | できない | できる |
| 見えるもの | 別のデスクトップ・別のホーム | 自分の環境 | コンソールと同じ画面 |
| 独立した作業 | **できる** | できる | できない |

**「リモートで独立した作業をしたい」なら専用アカウントが最適。**
「外から自分の環境・ファイルを触りたい」だけなら別ホームでは目的を果たせないので
Desktop Sharing を使う。

システム側の設定(xrdp 本体・Xwrapper・音声の autostart)は**全ユーザーに効く**ので、
追加作業はアカウント固有の分だけ:

```bash
sudo adduser --gecos "" john
sudo usermod -aG video,render john      # 管理作業もさせるなら sudo も足す

# Ubuntu セッションモード(このアカウントにも必要)
sudo -u john tee /home/john/.xsessionrc >/dev/null <<'EOS'
export DESKTOP_SESSION=ubuntu
export GNOME_SHELL_SESSION_MODE=ubuntu
export XDG_CURRENT_DESKTOP=ubuntu:GNOME
EOS

# 日本語入力(ログイン前でも dbus-run-session 経由で設定できる)
sudo -u john dbus-run-session -- sh -c "
  gsettings set org.gnome.desktop.input-sources sources \"[('ibus','mozc-jp'), ('xkb','jp')]\"
  gsettings set org.gnome.desktop.wm.keybindings switch-input-source \"['<Control><Shift>semicolon']\"
"
```

ホームは分かれるので、共有したいディレクトリが出てきたら共通グループ + setgid ディレクトリや
ACL で後付けする。

### 7. トラブルシュート早見表

| 症状 | ログに出るもの | 原因と対処 |
|---|---|---|
| 接続直後に切れる | `ERRCONNECT_CONNECT_CANCELLED` | パスワード未登録。ただし**ウィンドウを閉じただけでも同じコードが出る**ので、app.log の `Connection aborted by user` の有無で判別する |
| ログイン画面で弾かれる | `pam_authenticate failed` | **まずパスワードが正しいか疑う。** 設定差を探す前に検証すること |
| 画面が出ない | `waitforx: Unable to open display :10` | Xwrapper.config が `allowed_users=console` のまま |
| 一瞬で落ちる | `Window manager ... exited quickly (0 secs)` | コンソールに同一ユーザーがログイン中。ログアウトする |
| Dock も壁紙も無い | (ログ無し) | `~/.xsessionrc` が無い。作った後**ログアウト**して入り直す |
| 音が出ない | (ログ無し) | autostart の 2 ファイルが未配置。配置後**ログアウト**して入り直す |
| 黒画面のまま | (ログ無し) | コンポジタの再描画待ち。`xrdp-kick` 回避策(CLAUDE.md 参照) |

サーバー側のログは `/var/log/xrdp.log` と `/var/log/xrdp-sesman.log`(root のみ読める)。
セッション側は `~/.xorgxrdp.10.log` と `~/.xsession-errors`(ユーザーで読める)。

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

Tuned specifically for xrdp. Verified against both the 0.9 series (the default on Ubuntu 24.04) and the 0.10 series (GFX/H.264 capable), including audio redirection.

- **Requests GFX/H.264 with `/gfx:AVC444`** — GFX-capable xrdp 0.10 negotiates H.264 (without an explicit `/gfx`, the session stays on legacy RemoteFX)
- **Specifies `+rfx -nsc` as a fallback** — On GFX-less xrdp 0.9, RemoteFX is effectively the fastest codec. The NSCodec chosen by default has no NEON optimization in the Homebrew build on ARM Macs and renders very slowly, so it is disabled
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

## Setting up an Ubuntu host

**The same pitfalls were hit in order on two machines, so all of them are recorded here.**
Assumes Ubuntu 24.04 + GNOME with xrdp built from source. (The apt build, 0.9.x, has no
GFX/H.264 but does handle the Xwrapper and PAM parts for you.)

### 0. Decide which RDP server to use

Ubuntu ships gnome-remote-desktop, which is easy to confuse with xrdp.

| | xrdp | gnome-remote-desktop |
|---|---|---|
| Credentials | Ubuntu login | **Dedicated ones** set in GNOME Settings |
| NLA | Not required (`negotiate`) | **Required** |
| Session | New, independent | Remote Login = new / Desktop Sharing = **mirrors the console** |

**This app targets xrdp.** Connecting to gnome-remote-desktop by mistake yields errors such
as `SPNEGO failed 0xc00700ea`. If all you want is to see the same screen as the physical
console, use Desktop Sharing instead — it avoids the session-exclusivity constraint below.

### 1. Pick a port and free it

The convention here is **xrdp = 3390** (3389 tends to be taken by gnome-remote-desktop).
If it is occupied, move gnome-remote-desktop aside **without disabling it**:

```bash
grdctl rdp set-port 3391
grdctl rdp disable-port-negotiation
systemctl --user restart gnome-remote-desktop
```

### 2. Build and install

```bash
# libfuse-dev is FUSE 2; configure will not accept libfuse3-dev
sudo apt install -y autoconf libtool pkg-config nasm libssl-dev libpam0g-dev \
  libx11-dev libxfixes-dev libxrandr-dev libxml2-dev libjpeg-dev libfuse-dev \
  libmp3lame-dev libopus-dev libfdk-aac-dev libx264-dev libpixman-1-dev \
  xserver-xorg-dev xutils-dev libepoxy-dev libgbm-dev

git clone --depth 1 --branch v0.10.6 --recursive https://github.com/neutrinolabs/xrdp.git
cd xrdp && ./bootstrap
./configure --enable-fuse --enable-pixman --enable-mp3lame --enable-opus \
            --enable-fdkaac --enable-x264
make -j"$(nproc)" && sudo make install     # install BEFORE building xorgxrdp

git clone --depth 1 --branch v0.10.5 https://github.com/neutrinolabs/xorgxrdp.git
cd xorgxrdp && ./bootstrap
PKG_CONFIG_PATH=/usr/local/lib/pkgconfig ./configure --enable-glamor
make -j"$(nproc)" && sudo make install
```

- **Configuring xorgxrdp first always fails** (`Package 'xrdp' ... not found`): its `xrdp.pc`
  only exists once xrdp has been installed
- Dropping `--enable-fuse` removes drive redirection and clipboard file transfer
- Config lands in **`/etc/xrdp`** by default (`strict_locations` defaults to `no`);
  `--enable-strict-locations` puts it in `/usr/local/etc/xrdp`. Keep this consistent across
  machines or you will confuse yourself later

### 3. Configuration

#### (A) Required — effect verified in practice

```bash
# allow Xorg to start for a remote session; without it: "waitforx: Unable to open display :10"
printf 'allowed_users=anybody\nneeds_root_rights=yes\n' | sudo tee /etc/X11/Xwrapper.config

# start the Ubuntu session mode; without it there is no dock and no wallpaper
cat > ~/.xsessionrc <<'EOS'
export DESKTOP_SESSION=ubuntu
export GNOME_SHELL_SESSION_MODE=ubuntu
export XDG_CURRENT_DESKTOP=ubuntu:GNOME
EOS

sudo systemctl daemon-reload
sudo systemctl enable --now xrdp xrdp-sesman
```

Set `port` in `/etc/xrdp/xrdp.ini` to the port chosen above (e.g. `3390`).

#### (B) Matched to the reference machine — individual necessity NOT verified

These were applied as a batch to match the first machine (elwhite); **it was never isolated
whether each one matters**. They are harmless, so mirroring them is fine, but do not read
this as "it will not work without them".

| Setting | Value |
|---|---|
| `autorun` in `xrdp.ini` | `Xorg` (empty shows a module chooser on the login screen) |
| `[Xorg] ip` in `xrdp.ini` | `127.0.0.1` |
| `Section "Module"` of `/etc/X11/xrdp/xorg.conf` | add `Load "glamoregl"` |
| Groups | `sudo usermod -aG video,render "$USER"` |

### 4. Audio (the package alone is not enough)

**`sudo apt install libpipewire-0.3-modules-xrdp` does not produce sound on its own.**
The Ubuntu package (0.2-2) ships only the `.so` and **none of the machinery that loads it**.
Add these two files from upstream
[pipewire-module-xrdp](https://github.com/neutrinolabs/pipewire-module-xrdp):

| File | Mode |
|---|---|
| `/usr/libexec/pipewire-module-xrdp/load_pw_modules.sh` | `755 root:root` |
| `/etc/xdg/autostart/pipewire-xrdp.desktop` | `644 root:root` |

They can be fetched straight from upstream — no build required. The `.desktop` file is a
template, so `@pkglibexecdir@` has to be expanded:

```bash
sudo apt install -y libpipewire-0.3-modules-xrdp

BASE=https://raw.githubusercontent.com/neutrinolabs/pipewire-module-xrdp/v0.2/instfiles
sudo install -d /usr/libexec/pipewire-module-xrdp
curl -fsSL $BASE/load_pw_modules.sh \
  | sudo install -m 755 /dev/stdin /usr/libexec/pipewire-module-xrdp/load_pw_modules.sh
curl -fsSL $BASE/pipewire-xrdp.desktop.in \
  | sed 's#@pkglibexecdir@#/usr/libexec/pipewire-module-xrdp#' \
  | sudo install -m 644 /dev/stdin /etc/xdg/autostart/pipewire-xrdp.desktop
```

`load_pw_modules.sh` is md5 `2f6f8605d5641306abdf5e7faa324124` (2940 bytes, identical on
`devel` and `v0.2`, and byte-identical to the copy running on elwhite). Copying from a
working machine via `scp` is equally fine.

When it is working, `pw-cli -m -d load-module libpipewire-module-xrdp sink.node.latency=2048 ...`
runs inside the session.

### 5. Japanese input

macOS consumes the かな/英数 keys before any application sees them, so they never reach RDP.
Karabiner-Elements remaps them to another chord while `sdl-freerdp` is frontmost (see
CLAUDE.md). Configure the matching binding on **every** Ubuntu host you connect to:

```bash
gsettings set org.gnome.desktop.wm.keybindings switch-input-source \
  "['<Control><Shift>semicolon']"
```

### 6. Operational constraints

- **Only one GNOME session per user at a time** (`/run/user/<uid>/bus` is shared per user).
  If the physical console is logged in, the xrdp window manager exits immediately
  (`Window manager ... exited quickly (0 secs)`). See below for the way around it
- **xrdp keeps disconnected sessions and re-attaches on reconnect.** Anything read at session
  start (`.xsessionrc`, autostart entries) will **not** take effect by merely reconnecting —
  log out from the GNOME menu

### 6-1. Using the console and a remote session at once (recommended: a dedicated account)

The constraint above applies **per user**, so creating a separate account for remote use
solves it: a different uid means a different `/run/user/<uid>/bus`, and both GNOME sessions
can run simultaneously. glavine is set up this way (console = `smoltz`, remote = `john`).

**Pick a dedicated account when you want to do independent work remotely.** If you instead
want to reach your *own* environment and files from outside, a separate home does not achieve
that — use Desktop Sharing.

System-wide pieces (xrdp itself, Xwrapper, the audio autostart) apply to all users, so only
per-account setup remains:

```bash
sudo adduser --gecos "" john
sudo usermod -aG video,render john      # add sudo too if it should administer the box

sudo -u john tee /home/john/.xsessionrc >/dev/null <<'EOS'
export DESKTOP_SESSION=ubuntu
export GNOME_SHELL_SESSION_MODE=ubuntu
export XDG_CURRENT_DESKTOP=ubuntu:GNOME
EOS

sudo -u john dbus-run-session -- sh -c "
  gsettings set org.gnome.desktop.input-sources sources \"[('ibus','mozc-jp'), ('xkb','jp')]\"
  gsettings set org.gnome.desktop.wm.keybindings switch-input-source \"['<Control><Shift>semicolon']\"
"
```

Homes are separate; share directories later via a common group with setgid, or ACLs.

### 7. Troubleshooting

| Symptom | Log line | Cause / fix |
|---|---|---|
| Drops immediately | `ERRCONNECT_CONNECT_CANCELLED` | No password registered — but **closing the window yields the same code**; check app.log for `Connection aborted by user` to tell them apart |
| Rejected at login | `pam_authenticate failed` | **Suspect the password first**, before hunting config differences |
| No screen | `waitforx: Unable to open display :10` | `Xwrapper.config` still `allowed_users=console` |
| Dies at once | `Window manager ... exited quickly (0 secs)` | Same user logged in at the console |
| No dock/wallpaper | (none) | `~/.xsessionrc` missing — add it, then **log out** |
| No sound | (none) | The two autostart files are missing — add them, then **log out** |
| Black screen | (none) | Compositor repaint issue; see the `xrdp-kick` workaround in CLAUDE.md |

Server logs are `/var/log/xrdp.log` and `/var/log/xrdp-sesman.log` (root only). Session-side
logs are `~/.xorgxrdp.10.log` and `~/.xsession-errors` (readable as the user).
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
