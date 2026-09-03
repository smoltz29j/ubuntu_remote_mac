# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

このプロジェクトでは日本語でやり取りしてよい(UI・コメント・ドキュメントも日本語)。

## Project

**Ubuntu Remote Mac** — Ubuntu マシン(xrdp)へ接続するリモートデスクトップクライアントの macOS 版。
姉妹プロジェクト `~/claude/ubuntu_remote`(Windows / WPF + RDP ActiveX)の Mac 版であり、
機能仕様・設計判断の原典はそちらの CLAUDE.md を参照すること。
**ただし 2026-07-19 時点でこの Mac 上に `~/claude/ubuntu_remote` は存在しない**(別マシンにある)。
参照できない前提で読むこと。

## アーキテクチャ

macOS には Windows の RDP ActiveX に相当する「自ウィンドウに埋め込める RDP コントロール」が
無いため、Windows 版のタブ埋め込み構成は採らない。**軽量ランチャー構成**:

- `ubuntu_remote.py`(単一ファイル、標準ライブラリのみ)— tkinter のプロファイル管理 UI から
  **FreeRDP(`sdl-freerdp`)を子プロセスとして起動**する。セッション表示は FreeRDP 側の別ウィンドウ。
  `Session` クラスが 1 接続分のプロセス監視と自動再接続(異常終了時 最大5回・3秒間隔、
  60 秒以上安定していたらカウントリセット)を担当。ランチャーを閉じても接続中の
  sdl-freerdp ウィンドウは残る(再接続監視だけ止まる)。
- この路線は姉妹プロジェクト `~/claude/cam_viewer_mac`(tkinter UI + mpv 子プロセス)と同型。

## 実行

```bash
./run.sh                                    # tkinter を持つ python3 を探して起動
python3 -m py_compile ubuntu_remote.py      # 構文チェック(テストは置かない方針。動作確認は実機接続)
```

## 接続先マシン

どちらも SSH (22) が鍵認証で開いており、`ssh elwhite` / `ssh glavine` で入れる
(`~/.ssh/config` に登録済み)。サーバー側調査はこれで行う。
**どちらも「3390 = xrdp」に統一**してあるので、プロファイルのポートは 3390。

### elwhite (192.168.101.201)

- **3389 = GNOME リモートログイン**(gnome-remote-desktop システムサービス)。NLA 必須
  (`HYBRID_REQUIRED_BY_SERVER`)で、認証情報も Ubuntu ログインとは別の専用のもの。
  誤ってこちらに繋ぐと NLA 認証で `SPNEGO failed 0xc00700ea` になる。
- **3390 = xrdp 0.10.6(ソースビルド、GFX/H.264 対応)**。2026-07-05 に apt の 0.9.24 から
  移行済み。設定は **`/usr/local/etc/xrdp/`**(おそらく `--enable-strict-locations` 付きで
  ビルドされたと**推定** — configure の挙動からの逆算で、ビルドログでは未確認)。
  `/etc/xrdp/xrdp.ini` は旧 apt 版の残骸なので見ない。
- 物理コンソールは **GDM の待機画面のまま**(誰もログインしていない)。後述の排他制約のため
  この状態を維持すること。

### glavine (192.168.100.201) — 2026-07-19 に xrdp を導入

Ubuntu 24.04 / x86_64 / GPU は **AMD Radeon RX 6600**(NVIDIA ではないので nvenc は使えない)。
リモート用アカウントは **john**(uid 1001、ssh 鍵配置済み)。コンソールは smoltz が使う。
NIC は enp9s0 / MAC **`10:7c:61:45:68:41`** — サスペンドされたら `python3 tools/wake.py glavine`
で起こす(MAC はサスペンド中 ARP で引けないのでツールに静的登録してある)。
Mac と同一セグメント(192.168.100.x)なのでブロードキャストが直接届く。
WoL は NetworkManager で `magic` に設定済み(2026-07-19)だが、**実サスペンドからの
復帰は未検証**(BIOS 側の対応が未確認)。初回に空振りしたら物理復帰 + BIOS 設定を疑う。

- **3389 = Remote Login**(gnome-remote-desktop システムデーモン)
- **3390 = xrdp 0.10.6 + xorgxrdp 0.10.5**(ソースビルド)。設定は **`/etc/xrdp/`**
  — elwhite と**場所が違う**。上流の既定は `strict_locations no` で sysconfdir が `/etc` に
  なるため。glavine には apt 版の残骸が無いので `/etc/xrdp` で曖昧さは生じない。
- **3391 = Desktop Sharing**(gnome-remote-desktop ユーザーデーモン)。既定では 3389 が
  埋まっているため 3390 に自動退避していたので、`grdctl rdp set-port 3391` +
  `disable-port-negotiation` で移動させて 3390 を空けた。**無効化はしていない**ので
  コンソールのセッションを共有したいときはこちらが使える(要 NLA + 専用資格情報)。

## Ubuntu 26.x 以降(GNOME Wayland 専用)への移行方針

GNOME の X11 セッションは GNOME 49 (= Ubuntu 25.10) で削除済みで、それ以降の GNOME では
xrdp + xorgxrdp 構成は成立しない(対処 3 案の詳細は README のセットアップ手順冒頭)。

- **現状維持が基本方針**: elwhite / glavine は 24.04 LTS(2029-04 までサポート)のまま。
  OS アップグレードはしない。移行作業のトリガーは「25.10 以降のマシンを追加するとき」のみ。
- **プロトコルは RDP を変えない**(このアプリ・プロファイル管理・Karabiner 構成を温存)。
  第一候補 **gnome-remote-desktop の Remote Login**(GNOME 47+ でヘッドレス多ユーザー対応
  = 専用アカウント方式を引き継げる)、控えに xrdp + XFCE。
- **導入時の検証チェックリスト**(順に。途中で NG が出たら撤退基準へ):
  1. `grdctl --system` で Remote Login 有効化 + 専用資格情報 → プロファイルは NLA 有効で接続
  2. **H.264 が効くか** — NVIDIA は既知で OK、**AMD (VA-API) は未知数**。効かない場合、
     描画が実用に耐えるかで判断
  3. コンソール使用中に別アカウントのヘッドレスセッションが並立するか(専用アカウント方式の生命線)
  4. 日本語入力 — キーは RDP 経由なので `Ctrl+Shift+;` 方式はそのまま通るはず。実測で確認
  5. 音声 — g-r-d はネイティブ対応のはずで、pipewire-module-xrdp の配置は不要になる想定
  6. **自動再接続の終了コード** — `Session` のユーザー起因判定(exit 131 + ログ文字列)は
     xrdp 相手の実測値。g-r-d 相手では意味が変わる可能性が高いので実測し直す
  7. `+dynamic-resolution` — g-r-d は Display Control 対応のはずなので、xrdp で不可だった
     動的解像度が効く可能性がある。効くなら `/smart-sizing` との選択を再検討
- **撤退基準**: 2 が NG(H.264 不成立で描画が実用に耐えない)なら xrdp + XFCE に切り替える。
  その場合 GNOME を捨てるので `.xsessionrc` の Ubuntu セッションモードは不要になる。

## Ubuntu 側 xrdp をソースビルドするときの必須手当て

**手順そのものは README.md「接続先 Ubuntu のセットアップ手順」に順序立てて書いてある**
(コマンド列・トラブルシュート早見表つき)。新しいマシンを追加するときはそちらを見ること。
以下は「なぜそうするのか」「どのログがどの原因に対応するか」という診断側の情報。

apt 版なら自動でやってくれるがソースビルドでは自分で行う必要があるもの。glavine で全部踏んだ。

- **`/etc/X11/Xwrapper.config`** を `allowed_users=anybody` / `needs_root_rights=yes` にする。
  既定の `allowed_users=console` だとリモートからの Xorg 起動が拒否され、sesman ログに
  `waitforx: Unable to open display :10` → `X server failed to start` が出る。
- **`~/.xsessionrc`** に `DESKTOP_SESSION=ubuntu` / `GNOME_SHELL_SESSION_MODE=ubuntu` /
  `XDG_CURRENT_DESKTOP=ubuntu:GNOME` を書く。無いと素の GNOME で起動し、
  **ubuntu-dock / デスクトップアイコン / 壁紙が出ない**(パッケージは入っているのに使われない)。
  効いているかは実行中の gnome-shell の `/proc/<pid>/environ` を見れば分かる
  (`XDG_CURRENT_DESKTOP` が `GNOME` 止まりなら未反映、`ubuntu:GNOME` なら反映済み)。
- **`xrdp.ini`**: `port=3390`、`autorun=Xorg`(空だとログイン画面にモジュール選択が出る)、
  `[Xorg]` に `ip=127.0.0.1`。
- **`/etc/X11/xrdp/xorg.conf`**: Module セクションに `Load "glamoregl"` を追加。
- **グループ**: `video` と `render`(GPU/DRM アクセス)。
- ビルド順の罠: **xorgxrdp の configure は `xrdp.pc` を要求する**(`xrdp >= 0.9.80`)ので、
  **xrdp を `make install` してからでないと xorgxrdp を configure できない**。
- **`--enable-fuse` には FUSE **2**(`libfuse-dev`)が要る**。`libfuse3-dev` では
  `PKG_CHECK_MODULES([FUSE], [fuse >= 2.6])` が通らない。これを諦めると
  ドライブリダイレクト(`+drives`)とクリップボード経由のファイル転送が消える。
- **elwhite の `~/build_gpu_xrdp.sh` は使ってはいけない**。Nexarian fork の 2023-08-30
  スナップショット(0.9.80)を作る古い残骸で、稼働中の 0.10.6 とは別物。上流
  `neutrinolabs/xrdp` の `v0.10.6` タグ + `neutrinolabs/xorgxrdp` の `v0.10.5` を使う。
  configure は `--enable-fuse --enable-pixman --enable-mp3lame --enable-opus
  --enable-fdkaac --enable-x264`(rfxcodec は既定で有効、nvenc は上流に無い)。

## 音が出ないとき(glavine で踏んだ)

原因はほぼ一つ: apt の `libpipewire-0.3-modules-xrdp` は `.so` を **1 ファイル入れるだけ**で、
それをロードする仕組み(autostart + `load_pw_modules.sh`)を含まない。
**導入手順(上流 URL からの取得コマンド・md5)は README「4. 音を出す」を見る。**

診断:
- 正常ならセッション内で `pgrep -af libpipewire-module-xrdp` が
  `pw-cli -m -d load-module libpipewire-module-xrdp sink.node.latency=2048 ...` を返す
- 返さないなら autostart 2 ファイル(`/etc/xdg/autostart/pipewire-xrdp.desktop` →
  `/usr/libexec/pipewire-module-xrdp/load_pw_modules.sh`)の配置漏れ。ただし
  **autostart はセッション開始時にしか実行されない**ので、配置済みなのに鳴らない場合は
  ログアウト→再接続をしていないだけの可能性が高い。

## セッション開始直後に黒画面になるとき

elwhite には `~/.config/autostart/xrdp-kick.desktop` →
`~/.local/bin/xrdp-kick.sh` という回避策が入っている。xorgxrdp + GNOME で
コンポジタ出力がフレームバッファに反映されず黒く見える問題への対処で、
3/6/10 秒後に `xmessage` で 1x1 のウィンドウを一瞬マップして再描画を強制する。
glavine では発症していないので入れていない。出たら移植する。

## セッションの排他制約(重要)

**同一ユーザーの GNOME セッションは同時に 1 つしか存在できない**(`/run/user/<uid>/bus` が
ユーザー単位で共有されるため)。したがって:

- 物理コンソールにログインしたままだと **xrdp 側の WM が起動直後に終了する**。sesman ログに
  `Window manager (pid N) exited with non-zero exit code 1` /
  `exited quickly (0 secs)` が出る。**コンソールをログアウトすれば解決**する。
- **制約は「同一ユーザー」の話なので、リモート専用アカウントを作れば同時利用できる**
  (uid が違えば `/run/user/<uid>/bus` も別)。**glavine はこの方式**:
  コンソール=`smoltz` / リモート=`john`(uid 1001、`sudo,video,render`、ssh 鍵配置済み)。
  実測で smoltz の `:1` と john の `:10` が同時に動くことを確認済み(2026-07-19)。
  elwhite は従来どおり「コンソールを GDM 待機画面に保つ」方式。
- リモートで**自分の環境・ファイルそのもの**を触りたいなら専用アカウントでは目的を果たせない
  (ホームが別)。その場合は **Desktop Sharing(glavine なら 3391)** を使う
  — 新規セッションを作らずコンソールの画面をそのまま共有する。
- **xrdp は切断済みセッションを保持して再接続時に再アタッチする**
  (`KillDisconnected=false` / `DisconnectedTimeLimit=0`)。そのため `.xsessionrc` のような
  **セッション開始時に読まれる設定を変えたら、RDP を繋ぎ直すだけでは反映されない**。
  GNOME のメニューから**ログアウト**してセッションを破棄する必要がある。

## 接続がすぐ切れるとき(別クライアントとのセッション奪い合い)

xrdp は**同一セッションへ新しい接続が来ると古い接続を蹴る**。別マシンの RDP クライアントが
繋ぎっぱなしで「切断→自動再接続」を繰り返していると、こちらが繋いでも数秒〜数十分で蹴られ、
「安定して動かない」ように見える。2026-08-08 に実際に発生: Windows 機 Baldwin
(192.168.101.151)が elwhite の smoltz セッションへ 30 分〜1 時間おきに一晩で 33 回
再接続しており、Mac(Maddux)の接続が 6 秒で切られた。

- **蹴られた側の見え方**: サーバーが `ERRINFO_LOGOFF_BY_USER` を返し **exit=2**。
  クライアントログに「user logging off their session on the server」。exit=2 はユーザー起因
  扱いなのでランチャーは自動再接続しない(再接続しても蹴り合いの応酬になるだけなので妥当)。
- **診断**: sesman ログ(elwhite は `/var/log/xrdp-sesman.log`)の login request 行の **IP** と、
  `/var/log/xrdp.log` の **`Connected client computer name:`** 行で接続元マシンを特定する。
  自分の接続と数秒差で別 IP のログインが挟まっていれば奪い合い確定。
- **対処**: 蹴ってくる側のマシンで RDP クライアントを終了する(根本対処はこれのみ)。
  応急処置ならサーバーの ufw で該当 IP からの 3390 を一時遮断。
- **アプリ側ガード(2026-08-08 実装)**: `other_rdp_clients()` が接続前(初回・自動再接続とも)に
  ssh で接続先の `ss -Htn state established` を実行し、この Mac 以外の確立済み接続があれば
  接続を中止して「先客あり」ダイアログを出す。**こちらが誰かを蹴る事故は防げるが、
  接続後にこちらが蹴られるのは防げない**(それは相手側クライアントを止めるしかない)。
  ssh はプロファイルの host へ BatchMode(鍵認証)で入る。elwhite / glavine とも IP 直指定の
  ssh が通ることは実測確認済み。通らないホストでは判定不能(None)としてガードなしで接続する。

## 認証のトラブルシュート

`pam_authenticate failed: Authentication failure` は素直に「パスワードが違う」を意味する。
設定差を疑う前に**値そのものを検証する**こと(glavine で長時間これを取り違えた)。

- **RDP 画面での手入力は記号が化ける**。Mac は JIS キーボードだが macOS の入力ソースは ABC
  (US)で、そこへ `/kbd:layout:0x00000411` を宣言しているため記号の対応がずれる。
  パスワードに記号が含まれると手入力では通らないことがある。
- **検証は RDP を経由せずに行う**。`tools/register_password.py <プロファイル名>` が
  この検証を組み込んだ登録ツール — ssh 経由で接続先の `su` にパスワードを突き合わせ、
  **通った値だけ** Keychain に保存する(値は ssh の暗号化経路と stdin のみを通り `ps` に
  出ない)。`su - <自分> -c ...` を root で実行するとパスワードを聞かれないので、
  手動検証するなら**プロンプトが出たかを必ず確認**する。
- アプリの Keychain 読み書き自体は記号・引用符・バックスラッシュ・日本語すべてで
  往復を検証済み(正常)。ここを疑う必要はない。

## 環境の落とし穴(実機で確認済み)

- **RDP クライアントは `sdl-freerdp` を使う**(`brew install freerdp` に同梱)。同梱の
  `xfreerdp` は X11 前提で XQuartz が無いと動かない。オプション体系はほぼ共通
  (`/v: /u: /sec: /cert:` 等)だが、動的解像度は `+dynamic-resolution`(`+` 表記)。
- **SDL クライアントのウィンドウは常に「要求解像度 ÷ Retina ピクセル密度」のポイント数で
  開く**(4K+密度2 なら半分サイズ)。`/size:90%` のパーセント指定も `/smart-sizing:WxH` の
  ウィンドウサイズ指定も無視される(osascript の System Events で実測確認済み)。対策は
  接続後に AppleScript でウィンドウを画面サイズへ広げる(`Session._maximize_window`、
  `/smart-sizing` 併用で中身も追従)。**`+f`(フルスクリーン)は使わない** — キーボードが
  リモートに全部送られ Ctrl+Alt+Enter も効かず、ユーザーが脱出不能になる。
  また `/smart-sizing` と `+dynamic-resolution` は同時指定不可(パース時エラーで即終了)。
  xrdp 0.9 系は Display Control 非対応なので dynamic-resolution はどのみち無意味。
- **コーデックは `/gfx:AVC444 +rfx -nsc`**。sdl-freerdp は `/gfx` を明示しないと rdpgfx
  チャネル自体を載せず、xrdp 0.10 相手でもレガシー RemoteFX になる。さらに無指定の
  `/gfx` では RFX progressive 止まりで、**AVC444 明示で初めて H.264 になる**
  (`/var/log/xrdp.log` の `Matched H264 mode` → `starting h264 codec session gfx` で
  実機確認済み。brew ビルドは `WITH_GFX_H264=ON`/FFmpeg)。`+rfx` は GFX 非対応の
  xrdp 0.9 系向けフォールバック。NSCodec は ARM Mac の brew ビルドでは NEON 未実装
  (ログに `TODO: Implement neon optimized version`)で描画が著しく遅いため `-nsc`。
  初期ウィンドウは `/size:90%` で指定(既定だと 1024x768 で開いて小さすぎる)。
- **Python は Tk 8.6 以上を持つものを使う**(`run.sh` の `pick_python` が brew python を優先)。
  システム Python (`/usr/bin/python3`, 3.9) は Tk **8.5** で、最近の macOS では
  **ウィンドウが真っ黒に描画される**ため使えない。brew python は素では `_tkinter` を欠くので
  `brew install python-tk` が必要(インストール済み、Tk 9.0)。3.9 フォールバック時の保険として
  `from __future__ import annotations` は残している(`X | Y` 注釈は 3.9 では import 時に落ちる)。
- **Keychain 読み出しは `security find-generic-password -g` を使う**。`-w` は非 ASCII
  パスワードを hex 文字列で出力し、ASCII と区別がつかない。`-g` の `password:` 行は
  非ASCII → `0x<HEX> "..."` / ASCII → `"<生の値>"` で常に区別できる(hex に見える ASCII
  パスワードも引用形式になる)。書き込みは `security -i` に stdin でコマンドを渡し、
  平文が ps に出ないようにしている。

## 日本語入力(2026-07-19 実測で確定)

**リモート(Ubuntu)の ibus-mozc に日本語入力させる**方針。Mac 側 IME を使う `/kbd:unicode` は
SDL クライアントのセッションウィンドウでは機能しなかった。

- **`/kbd:layout:0x00000411`(日本語配列)を明示する。** 無指定だと macOS の入力ソース(ABC)
  から US 配列として申告され、記号配置がずれる。指定するとセッション側が
  `model: pc105 / layout: jp` になり、`Eisu_toggle`(66)・`Henkan_Mode`(129)・
  `Muhenkan`(131)・`Hiragana_Katakana`(208)の keysym に正しく解決される。
- **Mac の かな/英数 キーは使えない。** ことえりが有効だと macOS が IME 層より手前で消費し、
  Ubuntu 側には **1 イベントも到達しない**(押下時にメニューバーが あ/A で切り替わるのが証拠)。
  ことえりを無効化すれば通る可能性はあるが、Mac 側で日本語が打てなくなるので採らない。
- **`Ctrl+Space` 系の組み合わせも使えない。** キー自体は到達するが、**Ctrl の押下が主キーより
  約 37ms 遅れて届く**ため、押下の瞬間に判定する GNOME のグラブと永久に一致しない
  (8 回中 8 回とも `ctrl=0`)。macOS 側の「前の入力ソースを選択 = Ctrl+Space」が有効なのが原因。
  一方 **`Ctrl+Shift+<文字>` では修飾キーが正しく先行する**(実測 `ctrl=1 shift=1`)。
- **結論の構成**:
  - Ubuntu 側 — `gsettings set org.gnome.desktop.wm.keybindings switch-input-source
    "['<Control><Shift>semicolon']"`。入力ソースは `[('ibus','mozc-jp'), ('xkb','jp')]` の 2 つ
    なのでこれは**トグル**。真の ON/OFF が要るなら mozc 単独ソース化 + mozc キーマップの
    `IMEOn`/`IMEOff` が正攻法(未実施)。**接続先ごとに設定が要る** — Karabiner のルールは
    前面が `sdl-freerdp` なら接続先を問わず `Ctrl+Shift+;` を送るので、繋ぐ Ubuntu 側すべてで
    同じキーバインドにしておくこと(elwhite / glavine とも設定済み)。
  - Mac 側 — **変換ツール無し。`Ctrl+Shift+;` を直接押す**(2026-09-03 以降)。
    2026-09-03 までは **Karabiner-Elements** で `sdl-freerdp` 前面時のみ かな/英数 →
    `Ctrl+Shift+;` に変換していた(ルールは記録として `karabiner/ubuntu_remote_ime.json` に残す。
    `frontmost_application_if` は `file_paths` の末尾一致 `"sdl-freerdp$"` で書く必要があった)。
    撤去理由: Karabiner 16.x は Console-User-Server が **3 秒ごとにヘルパー 2 本 + launchctl を
    起動し続ける実装**(settings_window_guidance_manager の無条件タイマー、16.2.2 beta でも同じ。
    上流 #4493/#4496/#4518)で、常時プロセス生成の原因になっていたため。
    **撤去の実手順(2026-09-03 実施、次に外すときの落とし穴)**: `brew uninstall --cask
    karabiner-elements` はファイルと pkg レシートを消すだけで、起動中のデーモン・launchd 登録・
    DriverKit 拡張が残る。gui ドメインは `launchctl bootout/disable gui/$UID/<label>`、system
    ドメインは sudo で同様に bootout/disable。DriverKit 拡張(`org.pqrs.Karabiner-DriverKit-
    VirtualHIDDevice`)は **SIP 有効だと `systemextensionsctl uninstall` が拒否され、再起動でも
    消えない**。VirtualHIDDevice の pkg(GitHub releases)を入れ直して
    `scripts/uninstall/deactivate_driver.sh`(sudo 無し)→ `remove_files.sh`(sudo)を実行すると
    再起動不要で消える。`~/.config/karabiner/` は残る(害なし)。
  - ランチャー本体でこの変換をやるには CGEventTap(ctypes + CFRunLoop、約 200 行)が必要で、
    「入力監視」権限が **Python バイナリのパスに紐づく**ため brew python 更新で壊れる。採らない。

### かな/英数 を通す計画(未実施、2026-09-03 調査)

「macOS が消費する」は誤りの可能性が高い。SDL は Mac の かな(keyCode 104)/英数(102) を
`SDL_SCANCODE_LANG1/LANG2` として渡すが、**FreeRDP 3.30.0 以前の SDL3 クライアントがこの 2 つを
`RDP_SCANCODE_UNKNOWN` にして捨てていた**。FreeRDP 3.31.1(2026-08-29 のコミット
"support jp YEN/RO/EISUU/KANA keys")で かな → 0x72、英数 → 0x71 に対応。brew の freerdp は
3.31.1 が bottle 済み(2026-09-03 時点、依存パッケージ無し)。

ただし xrdp 0.10.6 + xorgxrdp 0.10.5 は **RDP スキャンコード + 8 を X keycode にするだけ**
(xorgxrdp `rdpKeyboard.c` `KbdAddEvent` の default 節)で、elwhite の `:10`(rules=base,
layout=jp)では keycode 121/122 に keysym が無い。そのため FreeRDP 側で keysym の載っている
スキャンコードへ付け替える:

| Mac キー | FreeRDP が送る | remap 先 | X keycode | keysym(実測 `xmodmap -pke`) |
|---|---|---|---|---|
| かな | 0x72 | 0x79 | 129 | `Henkan_Mode` |
| 英数 | 0x71 | 0x7B | 131 | `Muhenkan` |

手順:
1. `brew upgrade freerdp`(3.31.1 以上)
2. `build_rdp_args` に `"/kbd:remap:0x72=0x79,remap:0x71=0x7b"` を追加
   (SDL3 クライアントは `freerdp_keyboard_remap_key` を通すので remap が効く)
3. 接続先ごとに `gsettings set org.gnome.desktop.wm.keybindings switch-input-source
   "['Henkan_Mode', 'Muhenkan']"`(真の ON/OFF にするなら mozc キーマップで
   Henkan=IMEOn / Muhenkan=IMEOff)
4. 上の「キー到達を実測する手順」で keycode 129/131 が届くことを確認してから README を更新

**未確認**: macOS がことえり有効時に SDL ウィンドウへ かな/英数 の keyDown を渡すか。
以前の「1 イベントも到達しない」実測は FreeRDP 3.30 が捨てていた時のものなので、
3.31.1 で再測定が必要。届かなければ `Ctrl+Shift+;` 運用のまま。

#### 調査記録(2026-09-03、根拠の所在)

- **FreeRDP 側の脱落箇所**: `client/SDL/SDL3/sdl_input.cpp` の SDL→RDP 変換表。
  3.30.0 / 3.31.0 は `ENTRY(SDL_SCANCODE_LANG1, RDP_SCANCODE_UNKNOWN)`、
  `ENTRY(SDL_SCANCODE_LANG2, RDP_SCANCODE_UNKNOWN)`。3.31.1 は
  `LANG1 → RDP_SCANCODE_KANA_HANGUL (0x72)`、`LANG2 → RDP_SCANCODE_HANJA_KANJI (0x71)`、
  併せて `INTERNATIONAL3 → BACKSLASH_JP (¥)`、`INTERNATIONAL1 → ABNT_C1 (ろ)`。
  brew の sdl-freerdp は SDL3 リンク(`otool -L` で libSDL3 を確認)。
- **SDL 側**: `src/events/scancodes_darwin.h` で Mac keyCode 102 → `LANG2`(Eisu)、
  104 → `LANG1`(Kana)。SDL2/SDL3 とも同じ。
- **remap の適用箇所**: 同 `sdl_input.cpp` で `freerdp_keyboard_remap_key(_remapTable, rdp_scancode)`
  を通してから送信。`/kbd:remap:` は `/list:kbd-scancode` の 16 進で指定
  (例 `/kbd:remap:0x1e=0x1f`)。
- **xrdp 側の変換**: xrdp 0.10.6 にはスキャンコード→keycode 変換(`common/scancode.c`)が
  無く(0.11 系で追加)、そのまま xorgxrdp へ渡る。xorgxrdp 0.10.5 `xrdpkeyb/rdpKeyboard.c`
  `KbdAddEvent` は修飾・テンキー・Win キー等だけ特別扱いし、それ以外は
  `x_scancode = rdp_scancode + MIN_KEY_CODE(8)`。0x70〜0x7B は全部 default 節。
- **elwhite `:10` の keysym**(`setxkbmap -query`: rules=base, model=pc105, layout=jp。
  `xmodmap -pke` 実測):

  | keycode | keysym |
  |---|---|
  | 49 | Zenkaku_Hankaku |
  | 66 | Eisu_toggle(Caps 位置) |
  | 120, 121, 122 | (空)← かな 0x72 / 英数 0x71 / ひらがな 0x70 がそのまま落ちる先 |
  | 129 | Henkan_Mode |
  | 131 | Muhenkan |
  | 208 | Hiragana_Katakana |
  | 209 / 210 | Hangul / Hangul_Hanja |

  glavine も Ubuntu 24.04.4 + xrdp 0.10.6 で同構成(km-00000411.ini も同一)。
  なお `/etc/xrdp/km-00000411.ini` は Xvnc バックエンド用で、xorgxrdp 経路では参照されない。
- **Karabiner 撤去の根拠**: `Karabiner-Console-User-Server`(launchctl `forks = 2794` / 40 分)が
  `settings_window_guidance_manager::async_start()` の `std::chrono::seconds(3)` タイマーで
  `core-daemons-enabled` / `core-agents-enabled` / `running` ×2 をヘルパーアプリ経由で実行し続ける。
  16.2.0 stable、16.2.2 beta、main いずれも同じ。設定で止める手段は無い。アイドル時の合計負荷は
  Karabiner + trustd + backgroundtaskmanagementd で CPU 約 1.5%。
  同日の Mac フリーズ(プロセス生成の暴走)の発生源ではなかった(暴走中もこのループは 3 秒間隔のまま)が、
  用途がこのプロジェクトの かな/英数 変換だけだったので撤去した。

### キー到達を実測する手順(この種の調査の定石)

サーバー側で XI2 の raw イベントを取ると、**どのキーがどの修飾キー状態で届いたか**が確定できる。
`xev -root` はフォーカスが他ウィンドウにあると拾えないので使わない。

```bash
ssh smoltz@192.168.101.201 'export DISPLAY=:10 XAUTHORITY=$HOME/.Xauthority
  setsid nohup timeout 900 xinput test-xi2 --root > /tmp/xi2.log 2>&1 < /dev/null & disown'
# keycode は `xmodmap -pke` で keysym に引き当てる
```

- keycode **8**(`ISO_Level5_Shift`)が約 100ms 間隔で大量に出るが、これは押鍵と無関係の定常ノイズ。
- **Mac 側のキーログは取れない** — brew の FreeRDP は `WITH_DEBUG_SDL_KBD_EVENTS=OFF` ビルド。
  よって「Mac が食った」か「FreeRDP が送らなかった」かはサーバー側の到達有無とメニューバーの
  あ/A 表示で切り分ける。
- **ssh 越しの `pkill -f <パターン>` は自分自身を殺す**(リモートコマンド行が同じ文字列を含むため
  マッチする)。pid を直接 kill するか、パターンを分割して書く。

## Windows 版との対応表(実装済み)

| Windows 版 | Mac 版での対応 |
|---|---|
| プロファイル保存 `%APPDATA%\UbuntuRemote\profiles.json` | `~/Library/Application Support/UbuntuRemote/profiles.json`(パスワードは含めない) |
| パスワード暗号化 DPAPI (CurrentUser) | macOS Keychain(service=`UbuntuRemote`, account=プロファイルID)。**平文を JSON やログに残さない**。編集ダイアログでパスワード空欄 = 既存値維持、の規約も同じ |
| サーバー証明書検証なし(xrdp は自己署名) | `/cert:ignore` |
| NLA 既定オフ(Ubuntu xrdp は通常非対応)、プロファイル毎に選択可 | **既定は自動交渉(`/sec:` を渡さない)**。「NLA を強制する」チェックで `/sec:nla` |
| ユーザー名/パスワードを接続時に渡し xrdp ログイン画面を自動突破 | **`/args-from:stdin` で全引数(`/p:` 含む)を stdin から渡す**(1行=1引数、ps に平文を出さない)。`/from-stdin` は SDL クライアントでは GUI ダイアログになりパイプから受け取れないので使わない。パスワード未登録時は SDL の認証ダイアログに任せる |
| 自動再接続(非ユーザー起因の切断を最大5回リトライ) | FreeRDP の `+auto-reconnect` + ランチャー側 `Session` が非ユーザー起因の終了時のみ再起動。ユーザー起因 exit code {0,1,2,11,145} はリトライしない。**ウィンドウを閉じたときの exit はネットワーク断と同じ 131 (CONN_FAILED)** なので、app.log のこの接続分の出力に `Connection aborted by user` があるかで判別する |
| リサイズで解像度追従(SmartReconnect) | `+dynamic-resolution` |
| 全画面表示(F11 + mstsc 風の上端接続バー) | 「全画面」ボタン / F11 で AppleScript により AXFullScreen を反転(`+f` は脱出不能のため使わない)。ネイティブ全画面なのでマウスを上端に寄せればメニューバーから解除でき、これが接続バー相当の脱出手段 |
| ログ `%APPDATA%\UbuntuRemote\app.log` | `~/Library/Application Support/UbuntuRemote/app.log`(sdl-freerdp の stdout/stderr もここへ) |
