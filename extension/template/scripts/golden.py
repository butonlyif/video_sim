#!/usr/bin/env python3
"""golden.py — 各 IP 的按位精确金标准模型

复现 RTL 的定点运算，逐帧生成期望输出 expected.hex，供 compare.py 比对。
模型读取与仿真同一份 regcfg.hex（寄存器配置），保证配置一致。

用法:
  python scripts/golden.py --ip <ip> \
      --stimulus sim/testdata/stimulus.hex \
      --regcfg   sim/testdata/regcfg.hex \
      -W 64 -H 48 --frames N \
      --out sim/testdata/expected.hex
"""
import argparse

import numpy as np

# ── 每 IP 的比对配置（compare/verify 用）: 默认帧数 / 容差 / 容许失配比例 ──
CONFIG = {
    'gamma_corr':        {'frames': 1, 'tol': 0, 'frac': 0.0},
    'color_space_conv':  {'frames': 1, 'tol': 0, 'frac': 0.0},
    'defect_pixel_corr': {'frames': 1, 'tol': 0, 'frac': 0.0},
    'denoise':           {'frames': 1, 'tol': 0, 'frac': 0.0},
    'sharpen':           {'frames': 1, 'tol': 0, 'frac': 0.0},
    'contrast_enhance':  {'frames': 3, 'tol': 0, 'frac': 0.0},
    # AWB 的增益在帧内由 34 周期除法算出, 该帧首 ~34 像素为瞬态, 容许 2% 失配
    'auto_white_balance':{'frames': 3, 'tol': 1, 'frac': 0.02},
    'passthrough':       {'frames': 1, 'tol': 0, 'frac': 0.0},
}


# ── hex / regcfg I/O ──────────────────────────────────────────────

def read_frame(path, w, h):
    with open(path) as f:
        words = [int(line, 16) for line in f if line.strip()]
    px = np.array(words[:w * h], dtype=np.int64)
    r = (px >> 16) & 0xFF
    g = (px >> 8) & 0xFF
    b = px & 0xFF
    return np.stack([r, g, b], axis=-1).reshape(h, w, 3).astype(np.int64)


def write_frames(path, frames):
    with open(path, 'w') as f:
        for fr in frames:
            flat = fr.reshape(-1, 3).astype(np.int64)
            words = (flat[:, 0] << 16) | (flat[:, 1] << 8) | flat[:, 2]
            f.writelines(f"{int(v) & 0xFFFFFFFF:08x}\n" for v in words)


def read_writes(path):
    """返回有序的 (addr, data) 写序列（跳过哨兵行）。"""
    out = []
    try:
        with open(path) as f:
            for line in f:
                s = line.strip()
                if not s or s.upper().startswith('FFFFFFFFFF'):
                    continue
                v = int(s, 16)
                out.append(((v >> 32) & 0xFF, v & 0xFFFFFFFF))
    except FileNotFoundError:
        pass
    return out


def final_regs(writes, defaults):
    """last-write-wins 求最终寄存器值。"""
    regs = dict(defaults)
    for addr, data in writes:
        regs[addr] = data
    return regs


def clamp8(a):
    return np.clip(a, 0, 255).astype(np.int64)


# ── 窗口邻居 (sharpen/denoise/dpc 共用, 边界复制 = RTL 镜像) ──────────

def neighbors(img):
    p = np.pad(img, ((1, 1), (1, 1), (0, 0)), mode='edge')
    h, w = img.shape[:2]
    C = img
    N = p[0:h, 1:w + 1]       # 上一行同列
    W = p[1:h + 1, 0:w]       # 左邻
    E = p[1:h + 1, 2:w + 2]   # 右邻
    return C, N, E, W


# ── 各 IP 模型: model(frame, writes, frame_idx, state) -> out_frame ──

def m_passthrough(fr, writes, fi, st):
    return fr.copy()


def m_gamma(fr, writes, fi, st):
    regs = final_regs(writes, {0x04: 0x1, 0x10: 0x1})
    if not (regs[0x04] & 1) or (regs[0x04] >> 1) & 1:
        return fr.copy()
    sel = regs[0x10] & 0x3
    lut = np.arange(256, dtype=np.int64)
    if sel != 0:
        x = np.arange(256) / 255.0
        if sel == 1:
            y = np.where(x > 0, x ** (1 / 2.2), 0)
        elif sel == 2:
            y = np.where(x > 0, x ** (1 / 2.4), 0)
        else:  # sRGB
            y = np.where(x <= 0.0031308, 12.92 * x,
                         1.055 * np.power(np.maximum(x, 1e-12), 1 / 2.4) - 0.055)
        lut = np.floor(255.0 * y + 0.5).astype(np.int64)
        lut = np.clip(lut, 0, 255)
    return lut[fr]


def m_csc(fr, writes, fi, st):
    # 有序回放: MODE 写入加载预设, 之后 COEF/OFF 写入覆盖
    P_RGB2YUV = ([77, 150, 29, -43, -85, 128, 128, -107, -21], [0, 128, 128])
    P_YUV2RGB = ([256, 0, 359, 256, -88, -183, 256, 454, 0], [-180, 136, -227])
    coef = list(P_RGB2YUV[0]); off = list(P_RGB2YUV[1])
    enable, bypass = 1, 0
    for addr, data in writes:
        d16 = data & 0xFFFF
        sd = d16 - 0x10000 if d16 & 0x8000 else d16   # 符号还原
        if addr == 0x04:
            enable, bypass = data & 1, (data >> 1) & 1
        elif addr == 0x10:
            coef, off = ([list(P_RGB2YUV[0]), list(P_YUV2RGB[0])][data & 1],
                         [list(P_RGB2YUV[1]), list(P_YUV2RGB[1])][data & 1])
            coef, off = list(coef), list(off)
        elif 0x20 <= addr <= 0x40 and (addr & 3) == 0:
            coef[(addr - 0x20) >> 2] = sd
        elif addr in (0x44, 0x48, 0x4C):
            off[(addr - 0x44) >> 2] = sd
    if not enable or bypass:
        return fr.copy()
    M = np.array(coef, dtype=np.int64).reshape(3, 3)
    O = np.array(off, dtype=np.int64)
    flat = fr.reshape(-1, 3)
    acc = flat @ M.T                      # (N,3)
    sh = np.right_shift(acc, 8) + O       # 算术右移 + 偏置
    return clamp8(sh).reshape(fr.shape)


def m_sharpen(fr, writes, fi, st):
    regs = final_regs(writes, {0x04: 0x1, 0x10: 0x4})
    if not (regs[0x04] & 1) or (regs[0x04] >> 1) & 1:
        return fr.copy()
    k = regs[0x10] & 0xF
    C, N, E, W = neighbors(fr)
    lap = 4 * C - 2 * N - E - W           # 有符号
    adj = lap * k
    out = C + np.right_shift(adj, 3)      # 算术右移
    return clamp8(out)


def m_denoise(fr, writes, fi, st):
    regs = final_regs(writes, {0x04: 0x1, 0x10: 0x8})
    if not (regs[0x04] & 1) or (regs[0x04] >> 1) & 1:
        return fr.copy()
    k = min(regs[0x10] & 0xF, 8)
    C, N, E, W = neighbors(fr)
    filt = np.right_shift(4 * C + 2 * N + E + W, 3)
    adj = (filt - C) * k
    out = C + np.right_shift(adj, 3)
    return clamp8(out)


def m_dpc(fr, writes, fi, st):
    regs = final_regs(writes, {0x04: 0x1, 0x10: 0x60})
    if not (regs[0x04] & 1) or (regs[0x04] >> 1) & 1:
        return fr.copy()
    thr = regs[0x10] & 0xFF
    C, N, E, W = neighbors(fr)
    dmin = np.minimum(np.minimum(np.abs(C - N), np.abs(C - E)), np.abs(C - W))
    avg = np.right_shift((N + E + W) * 85, 8)
    return np.where(dmin > thr, clamp8(avg), C)


def m_awb(fr, writes, fi, st):
    regs = final_regs(writes, {0x04: 0x5, 0x10: 0x100, 0x14: 0x100,
                               0x18: 0x100, 0x1C: 0})
    enable, bypass, auto = regs[0x04] & 1, (regs[0x04] >> 1) & 1, (regs[0x04] >> 2) & 1
    # 增益取自上一帧统计（首帧 256）; 各帧输入相同, 故 fi>=1 增益恒定
    if fi == 0 or not enable or bypass:
        gr, gg, gb = 256, 256, 256
    elif auto:
        sr = int(fr[:, :, 0].sum()); sg = int(fr[:, :, 1].sum()); sb = int(fr[:, :, 2].sum())
        tot = sr + sg + sb
        gr = (tot << 8) // (3 * sr) if sr else 256
        gb = (tot << 8) // (3 * sb) if sb else 256
        gg = 256
    else:
        PRE = {1: (256, 256, 256), 2: (307, 256, 218),
               3: (218, 256, 307), 4: (333, 256, 166)}
        gr, gg, gb = PRE.get(regs[0x1C] & 0x7, (regs[0x10], regs[0x14], regs[0x18]))
    g = np.array([gr, gg, gb], dtype=np.int64)
    return clamp8(np.right_shift(fr * g, 8))


def m_contrast(fr, writes, fi, st):
    regs = final_regs(writes, {0x04: 0x1, 0x10: 0x8})
    enable, bypass = regs[0x04] & 1, (regs[0x04] >> 1) & 1
    k = min(regs[0x10] & 0xF, 8)
    # LUT 取自 2 帧前的直方图(乒乓), fi<2 未生效=直通; 各帧输入相同
    if fi < 2 or not enable or bypass:
        return fr.copy()
    y = np.right_shift(fr[:, :, 0] + 2 * fr[:, :, 1] + fr[:, :, 2], 2)
    hist = np.bincount(y.ravel(), minlength=256)
    total = fr.shape[0] * fr.shape[1]
    recip = (255 << 16) // total
    cdf = np.cumsum(hist)
    lut = np.minimum(255, np.right_shift(cdf * recip, 16)).astype(np.int64)
    mapped = lut[fr]
    adj = (mapped - fr) * k
    out = fr + np.right_shift(adj, 3)
    return clamp8(out)


MODELS = {
    'passthrough': m_passthrough, 'gamma_corr': m_gamma,
    'color_space_conv': m_csc, 'sharpen': m_sharpen, 'denoise': m_denoise,
    'defect_pixel_corr': m_dpc, 'auto_white_balance': m_awb,
    'contrast_enhance': m_contrast,
}


# ── 去中心化金标准发现(平台改进 #4) ─────────────────────────────────
# 扫描 rtl/<ip>/golden.py, 动态导入并覆盖内置 MODELS/CONFIG。新 IP 只需把
# golden.py 放到自己目录(导出 model + 可选 CONFIG)即自动接入, 无需改本公共文件。
# 内置 MODELS/CONFIG 作为迁移期回退, 找不到对应 rtl/<ip>/golden.py 时仍可用。
# 各 IP 模块可 `import golden` 复用 read_frame/neighbors/clamp8/final_regs 等辅助函数。

def _discover_ip_models():
    import glob
    import importlib.util
    import os
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for path in sorted(glob.glob(os.path.join(root, 'rtl', '*', 'golden.py'))):
        ip = os.path.basename(os.path.dirname(path))
        spec = importlib.util.spec_from_file_location(f"golden_{ip}", path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as e:  # 单个 IP 模型出错不应拖垮整个加载
            print(f"WARN: 加载 rtl/{ip}/golden.py 失败: {e}", file=sys.stderr)
            continue
        if hasattr(mod, 'model'):
            MODELS[ip] = mod.model
        if hasattr(mod, 'CONFIG'):
            CONFIG[ip] = mod.CONFIG


_discover_ip_models()


def generate(ip, frame, frames, writes):
    model = MODELS[ip]
    return [model(frame, writes, fi, None) for fi in range(frames)]


def main():
    ap = argparse.ArgumentParser(description="金标准模型 → expected.hex")
    ap.add_argument('--ip', required=True, choices=sorted(MODELS))
    ap.add_argument('--stimulus', required=True)
    ap.add_argument('--regcfg', default=None)
    ap.add_argument('-W', '--width', type=int, required=True)
    ap.add_argument('-H', '--height', type=int, required=True)
    ap.add_argument('--frames', type=int, default=1)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    frame = read_frame(args.stimulus, args.width, args.height)
    writes = read_writes(args.regcfg) if args.regcfg else []
    outs = generate(args.ip, frame, args.frames, writes)
    write_frames(args.out, outs)
    print(f"OK: {args.out}  {args.ip}  {args.width}x{args.height} x{args.frames}帧")


if __name__ == '__main__':
    main()
