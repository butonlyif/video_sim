"""analyze_video.py — 视频时序分析

逐帧计算输入(stimulus)与输出(result)的质量指标, 输出时间序列 JSON,
供控制台画"指标随帧变化"曲线。指标与图像分析一致 (锐度/亮度/RGB/PSNR),
额外给出逐帧 PSNR 反映时域稳定性。
"""
import argparse
import json

import cv2
import numpy as np


def load_frames(path, w, h, frames):
    with open(path) as f:
        words = np.array([int(line, 16) for line in f if line.strip()],
                         dtype=np.uint32)
    per = w * h
    out = []
    for k in range(min(frames, words.size // per)):
        seg = words[k * per:(k + 1) * per]
        r = ((seg >> 16) & 0xFF).astype(np.uint8)
        g = ((seg >> 8) & 0xFF).astype(np.uint8)
        b = (seg & 0xFF).astype(np.uint8)
        out.append(np.stack([b, g, r], axis=-1).reshape(h, w, 3))
    return out


def sharp(img):
    return round(float(cv2.Laplacian(
        cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()), 1)


def luma(img):
    return round(float(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).mean()), 1)


def psnr(a, b):
    mse = np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2)
    return None if mse == 0 else round(10 * np.log10(255.0 ** 2 / mse), 2)


def main():
    ap = argparse.ArgumentParser(description="视频时序分析")
    ap.add_argument('--stimulus', required=True)
    ap.add_argument('--result', required=True)
    ap.add_argument('-W', '--width', type=int, required=True)
    ap.add_argument('-H', '--height', type=int, required=True)
    ap.add_argument('--frames', type=int, required=True)
    ap.add_argument('--report', required=True)
    args = ap.parse_args()

    ins = load_frames(args.stimulus, args.width, args.height, args.frames)
    outs = load_frames(args.result, args.width, args.height, args.frames)
    n = min(len(ins), len(outs))

    per_frame = []
    for k in range(n):
        a, b = ins[k], outs[k]
        per_frame.append({
            'idx': k,
            'sharp_in': sharp(a), 'sharp_out': sharp(b),
            'luma_in': luma(a), 'luma_out': luma(b),
            'rgb_out': [round(float(b[:, :, 2].mean()), 1),
                        round(float(b[:, :, 1].mean()), 1),
                        round(float(b[:, :, 0].mean()), 1)],
            'psnr': psnr(a, b),
        })

    report = {'frames': n, 'resolution': f"{args.width}x{args.height}",
              'per_frame': per_frame}
    import os
    os.makedirs(os.path.dirname(args.report) or '.', exist_ok=True)
    with open(args.report, 'w') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"OK: {args.report}  {n} 帧时序指标")


if __name__ == '__main__':
    main()
