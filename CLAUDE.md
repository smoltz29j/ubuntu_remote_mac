# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

このプロジェクトでは日本語でやり取りしてよい(UI・コメント・ドキュメントも日本語)。

## Project

**Ubuntu Remote Mac** — Ubuntu マシン(xrdp)へ接続するリモートデスクトップクライアントの macOS 版。
姉妹プロジェクト `~/claude/ubuntu_remote`(Windows / WPF + RDP ActiveX)の Mac 版であり、
機能仕様・設計判断の原典はそちらの CLAUDE.md を参照すること。

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

## 実機 elwhite (192.168.101.201) の構成

RDP サーバーが 2 つ動いている。**繋ぐべきは 3390 の xrdp**(Ubuntu のログイン情報で入れる):

- **3389 = GNOME リモートログイン**(gnome-remote-desktop システムサービス)。NLA 必須
  (`HYBRID_REQUIRED_BY_SERVER`)で、認証情報も Ubuntu ログインとは別の専用のもの。
  誤ってこちらに繋ぐと NLA 認証で `SPNEGO failed 0xc00700ea` になる。
- **3390 = xrdp 0.10.6(ソースビルド、GFX/H.264 対応)**。2026-07-05 に apt の 0.9.24 から
  移行済み。稼働中の設定は `/usr/local/etc/xrdp/xrdp.ini`(`port=3390`、
  `security_layer=negotiate`)と `/usr/local/etc/xrdp/gfx.toml`。`/etc/xrdp/xrdp.ini` は
  旧 apt 版の残骸なので見ない。詳細は Windows 版 CLAUDE.md の同セクション参照。
- SSH (22) も開いており鍵認証で入れる(`ssh smoltz@192.168.101.201`)。サーバー側調査はこれで。

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
    `IMEOn`/`IMEOff` が正攻法(未実施)。
  - Mac 側 — **Karabiner-Elements** で `sdl-freerdp` 前面時のみ かな/英数 → `Ctrl+Shift+;` に変換。
    ルールは `~/.config/karabiner/assets/complex_modifications/ubuntu_remote_ime.json`。
    **`sdl-freerdp` は `.app` バンドルではなくバンドル ID を持たない**ため、
    `frontmost_application_if` は `bundle_identifiers` ではなく `file_paths` の
    末尾一致(`"sdl-freerdp$"`)で書く(パスにバージョン番号が入るので前方一致は不可)。
  - ランチャー本体でこの変換をやるには CGEventTap(ctypes + CFRunLoop、約 200 行)が必要で、
    「入力監視」権限が **Python バイナリのパスに紐づく**ため brew python 更新で壊れる。
    採らずに Karabiner に寄せた。

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
