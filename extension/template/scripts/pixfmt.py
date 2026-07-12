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
  YUV444  YCbCr 全采样,  24 位字 {Y,Cb,Cr}            (每像素一个字)
  YUV422  YCbCr 4:2:2,   16 位字 {Y,C} (YUYV 行内交织)  (每像素一个字, 色度水平减半)
  YUV420  YCbCr 4:2:0,   16 位字 {Y,C} (交织近似)        (每像素一个字, 色度 2x2 块共享)

YUV 三种格式均"每像素一个字", 兼容现有逐字 source/sink/分析链。色度用 BT.601
全范围 (JPEG) 转换。422/420 区别仅在打包时色度的下采样邻域 (1x2 vs 2x2);
解包时同一逻辑 (偶列存 Cb / 奇列存 Cr, 成对还原)。422/420 假定宽为偶 (奇宽按边缘补齐)。

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
    'YUV444': (3, 24),
    'YUV422': (3, 16),
    'YUV420': (3, 16),
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

_YUV = {'YUV444', 'YUV422', 'YUV420'}   # YCbCr 子采样格式 (每像素一个字)

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


# ---- YCbCr (BT.601 全范围 / JPEG) 与色度下采样 -----------------------------

def _to8(a):
    return np.clip(np.round(a), 0, 255).astype(np.uint32)


def _rgb_to_ycbcr(img_bgr):
    b = img_bgr[:, :, 0].astype(np.float64)
    g = img_bgr[:, :, 1].astype(np.float64)
    r = img_bgr[:, :, 2].astype(np.float64)
    y = 0.299 * r + 0.587 * g + 0.114 * b
    cb = -0.168736 * r - 0.331264 * g + 0.5 * b + 128.0
    cr = 0.5 * r - 0.418688 * g - 0.081312 * b + 128.0
    return y, cb, cr


def _ycbcr_to_bgr(y, cb, cr):
    y = y.astype(np.float64); cb = cb.astype(np.float64); cr = cr.astype(np.float64)
    r = y + 1.402 * (cr - 128.0)
    g = y - 0.344136 * (cb - 128.0) - 0.714136 * (cr - 128.0)
    b = y + 1.772 * (cb - 128.0)
    to8 = lambda a: np.clip(np.round(a), 0, 255).astype(np.uint8)
    return np.stack([to8(b), to8(g), to8(r)], axis=-1)


def _avg_h(a):
    """色度水平 1x2 配对均值, 还原回原宽 (成对同值)。奇宽按边缘补齐。"""
    h, w = a.shape
    if w & 1:
        a = np.concatenate([a, a[:, -1:]], axis=1)
    we = a.shape[1]
    m = a.reshape(h, we // 2, 2).mean(axis=2)
    return np.repeat(m, 2, axis=1)[:, :w]


def _avg_2x2(a):
    """色度 2x2 块均值, 还原回原尺寸 (块内同值)。奇宽/奇高按边缘补齐。"""
    h, w = a.shape
    if h & 1:
        a = np.concatenate([a, a[-1:, :]], axis=0)
    if w & 1:
        a = np.concatenate([a, a[:, -1:]], axis=1)
    he, we = a.shape
    m = a.reshape(he // 2, 2, we // 2, 2).mean(axis=(1, 3))
    return np.repeat(np.repeat(m, 2, axis=0), 2, axis=1)[:h, :w]


def _pack_yuv(img_bgr, fmt):
    y, cb, cr = _rgb_to_ycbcr(img_bgr)
    if fmt == 'YUV444':                          # 全采样: {Y,Cb,Cr} 24 位
        words = (_to8(y) << 16) | (_to8(cb) << 8) | _to8(cr)
        return words.flatten()
    cb = _avg_h(cb) if fmt == 'YUV422' else _avg_2x2(cb)
    cr = _avg_h(cr) if fmt == 'YUV422' else _avg_2x2(cr)
    h, w = y.shape                               # 偶列存 Cb, 奇列存 Cr (YUYV 风格)
    c = np.empty((h, w))
    c[:, 0::2] = cb[:, 0::2]
    c[:, 1::2] = cr[:, 1::2]
    words = (_to8(y) << 8) | _to8(c)             # {Y, C} 16 位
    return words.flatten()


def _expand_chroma(c):
    """偶列 Cb / 奇列 Cr → 成对还原出整幅 Cb, Cr。奇宽按边缘补齐。"""
    h, w = c.shape
    pad = w & 1
    if pad:
        c = np.concatenate([c, c[:, -1:]], axis=1)
    cb = c.copy(); cr = c.copy()
    cb[:, 1::2] = c[:, 0::2]                      # 奇列取左邻偶列的 Cb
    cr[:, 0::2] = c[:, 1::2]                      # 偶列取右邻奇列的 Cr
    if pad:
        cb = cb[:, :w]; cr = cr[:, :w]
    return cb, cr


def _unpack_yuv(words, fmt, h, w):
    words = words.astype(np.uint32)
    if fmt == 'YUV444':
        y = ((words >> 16) & 0xFF).reshape(h, w)
        cb = ((words >> 8) & 0xFF).reshape(h, w)
        cr = (words & 0xFF).reshape(h, w)
        return _ycbcr_to_bgr(y, cb, cr).reshape(h, w, 3)
    y = ((words >> 8) & 0xFF).reshape(h, w)
    c = (words & 0xFF).reshape(h, w)
    cb, cr = _expand_chroma(c)
    return _ycbcr_to_bgr(y, cb, cr).reshape(h, w, 3)


def pack(img_bgr, fmt):
    """HxWx3 BGR uint8 → 一维 uint32 hex 字数组。"""
    if fmt in _YUV:
        return _pack_yuv(img_bgr, fmt)
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
    if fmt in _YUV:
        return _unpack_yuv(words, fmt, h, w)
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
