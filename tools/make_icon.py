#!/usr/bin/env python3
"""Ubuntu Remote.app のアイコン(1024x1024 PNG)を生成する。標準ライブラリのみ。

図案: Ubuntu を示すオレンジのグラデーション角丸スクエアに、リモートデスクトップを
示す白いディスプレイ。Ubuntu の Circle of Friends は商標なので使わない。
SDF(符号付き距離場)+ 距離ベースのアンチエイリアスで描くので外部ライブラリ不要。

使い方:
    python3 tools/make_icon.py /path/to/icon_1024.png
その後 .icns 化(コメントは README でなくここに残す):
    mkdir AppIcon.iconset
    for s in 16 32 128 256 512; do
      sips -z $s $s icon_1024.png --out AppIcon.iconset/icon_${s}x${s}.png
      d=$((s*2)); sips -z $d $d icon_1024.png --out AppIcon.iconset/icon_${s}x${s}@2x.png
    done
    iconutil -c icns AppIcon.iconset -o "Ubuntu Remote.app/Contents/Resources/AppIcon.icns"
"""
import struct
import sys
import zlib

N = 1024


def sdf_rrect(px, py, x0, y0, x1, y1, r):
    """角丸長方形の符号付き距離(負=内側)。"""
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    hx, hy = (x1 - x0) / 2 - r, (y1 - y0) / 2 - r
    qx = abs(px - cx) - hx
    qy = abs(py - cy) - hy
    ax = qx if qx > 0 else 0.0
    ay = qy if qy > 0 else 0.0
    outside = (ax * ax + ay * ay) ** 0.5
    inside = qx if qx > qy else qy
    return outside - r if outside > 0 else inside - r


def aa(d):
    """距離 → 被覆率(1.5px 幅でスムーズに)。"""
    a = 0.5 - d / 1.5
    return 0.0 if a < 0 else (1.0 if a > 1 else a)


def lerp(c0, c1, t):
    return tuple(c0[i] + (c1[i] - c0[i]) * t for i in range(3))


def blend(dst, src, alpha):
    return tuple(dst[i] + (src[i] - dst[i]) * alpha for i in range(3))


# 配色(Ubuntu オレンジ系)
TOP = (240, 129, 58)      # 上端
BOTTOM = (222, 74, 22)    # 下端
SCREEN = (206, 69, 23)    # 画面内(白フチとのコントラスト用に少し暗く)
WHITE = (255, 255, 255)

rows = []
for y in range(N):
    row = bytearray()
    row.append(0)  # PNG filter: none
    for x in range(N):
        px, py = x + 0.5, y + 0.5
        d_bg = sdf_rrect(px, py, 100, 100, 924, 924, 184)
        a_bg = aa(d_bg)
        if a_bg <= 0:
            row += b"\x00\x00\x00\x00"
            continue
        t = (py - 100) / 824
        t = 0.0 if t < 0 else (1.0 if t > 1 else t)
        col = lerp(TOP, BOTTOM, t)
        # ディスプレイのグリフ(枠 → 画面内 → 脚 → 台座)
        if 230 < px < 794 and 274 < py < 756:
            a = aa(sdf_rrect(px, py, 252, 296, 772, 636, 40))   # 枠
            if a > 0:
                col = blend(col, WHITE, a)
            a = aa(sdf_rrect(px, py, 282, 326, 742, 606, 24))   # 画面内
            if a > 0:
                col = blend(col, SCREEN, a)
            a = aa(sdf_rrect(px, py, 480, 636, 544, 694, 8))    # 脚
            if a > 0:
                col = blend(col, WHITE, a)
            a = aa(sdf_rrect(px, py, 368, 694, 656, 734, 20))   # 台座
            if a > 0:
                col = blend(col, WHITE, a)
        row += bytes((int(col[0] + 0.5), int(col[1] + 0.5), int(col[2] + 0.5),
                      int(a_bg * 255 + 0.5)))
    rows.append(bytes(row))


def chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data)))


out = sys.argv[1] if len(sys.argv) > 1 else "icon_1024.png"
ihdr = struct.pack(">IIBBBBB", N, N, 8, 6, 0, 0, 0)  # 8bit RGBA
idat = zlib.compress(b"".join(rows), 9)
with open(out, "wb") as f:
    f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", idat) + chunk(b"IEND", b""))
print(f"書き出し: {out}")
