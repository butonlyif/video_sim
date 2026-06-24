#!/usr/bin/env python3
"""pixfmt.py — 像素格式定义 (激励/还原/分析统一走这里)

平台导入已有工程时, IP 的数据格式由其 tdata 位宽决定, 不再固定 RGB888。
每种格式定义: 通道数、hex 字宽(位数)、图像↔hex字 的打包/解包。

支持格式:
  RGB888  3 通道, 32 位字 {8'd0,R,G,B}  (平台默认, 向后兼容)
  RGB24   3 通道, 24 位字 {R,G,B}
  RAW8    1 通道,  8 位字  (RAW Bayer / 灰度, 单字节)
  GRAY8   1 通道,  8 位字  (= RAW8, 仅语义区分)
  RAW16   1 通道, 16 位字  (RAW10/12/16 的容器)

作为库使用:
  import pixfmt
  fmt = pixfmt.from_width(8)          # -> 'RAW8'
  words = pixfmt.pack(img_bgr, fmt)   # HxWx3 BGR uint8 -> 一维 uint32 字数组
  img   = pixfmt.unpack(words, fmt, h, w)  # 字数组 -> HxWx3 BGR uint8
"""
import numpy as np

# 格式 → (通道数, hex 字位宽)。Bayer 为单通道 8 位, 但按马赛克排布取色。
_FMT = {
    'RGB888': (3, 32),
    'RGB24':  (3, 24),
    'RAW8':   (1, 8),
    'GRAY8':  (1, 8),
    'RAW16':  (1, 16),
    'BAYER_RGGB': (1, 8),
    'BAYER_GRBG': (1, 8),
    'BAYER_BGGR': (1, 8),
    'BAYER_GBRG': (1, 8),
}

# Bayer 2x2 排列: pattern[行%2][列%2] = 该位置保留的颜色通道
_BAYER = {
    'BAYER_RGGB': (('R', 'G'), ('G', 'B')),
    'BAYER_GRBG': (('G', 'R'), ('B', 'G')),
    'BAYER_BGGR': (('B', 'G'), ('G', 'R')),
    'BAYER_GBRG': (('G', 'B'), ('R', 'G')),
}
_CH = {'B': 0, 'G': 1, 'R': 2}   # OpenCV BGR 通道下标

FORMATS = tuple(_FMT.keys())


def is_known(fmt):
    return fmt in _FMT


def channels(fmt):
    return _FMT.get(fmt, _FMT['RGB888'])[0]


def word_bits(fmt):
    return _FMT.get(fmt, _FMT['RGB888'])[1]


def hex_digits(fmt):
    return (word_bits(fmt) + 3) // 4


def from_width(bits):
    """由 tdata 位宽推断格式 (导入时用)。未知位宽回退 RGB888。"""
    if bits == 8:
        return 'RAW8'
    if bits in (10, 12, 16):
        return 'RAW16'
    if bits == 24:
        return 'RGB24'
    if bits == 32:
        return 'RGB888'
    return 'RGB888'


def pack(img_bgr, fmt):
    """HxWx3 BGR uint8 → 一维 uint32 hex 字数组。"""
    b = img_bgr[:, :, 0].astype(np.uint32)
    g = img_bgr[:, :, 1].astype(np.uint32)
    r = img_bgr[:, :, 2].astype(np.uint32)
    if fmt in _BAYER:                            # Bayer 马赛克: 按位置取单通道
        h, w = b.shape
        out = np.zeros((h, w), np.uint32)
        pat = _BAYER[fmt]
        for ry in (0, 1):
            for cx in (0, 1):
                ch = _CH[pat[ry][cx]]
                out[ry::2, cx::2] = img_bgr[ry::2, cx::2, ch]
        return out.flatten()
    if channels(fmt) == 3:                       # RGB: {R,G,B} (高位 R)
        words = (r << 16) | (g << 8) | b
    else:                                        # 单通道: 用亮度 (BT.601)
        gray = (0.299 * r + 0.587 * g + 0.114 * b).round().astype(np.uint32)
        words = gray & ((1 << word_bits(fmt)) - 1)
    return words.flatten()


def unpack(words, fmt, h, w):
    """一维 hex 字数组 → HxWx3 BGR uint8 (单通道复制到三通道便于显示)。"""
    words = words.astype(np.uint32)
    if channels(fmt) == 3:
        r = ((words >> 16) & 0xFF).astype(np.uint8)
        g = ((words >> 8) & 0xFF).astype(np.uint8)
        b = (words & 0xFF).astype(np.uint8)
        return np.stack([b, g, r], axis=-1).reshape(h, w, 3)
    # 单通道: 取低 bits, 若 >8 位则右移到 8 位显示
    bits = word_bits(fmt)
    v = words & ((1 << bits) - 1)
    if bits > 8:
        v = v >> (bits - 8)
    v = v.astype(np.uint8)
    return np.stack([v, v, v], axis=-1).reshape(h, w, 3)
