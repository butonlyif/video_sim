#!/usr/bin/env python3
"""dump_frames.py — 多帧 hex 拆成逐帧 PNG (供控制台帧级预览/分析)

从 stimulus.hex / result.hex (N 帧 RGB888) 提取每一帧为 PNG, 命名 frame_000.png …
帧数据无损 (即 DUT 实际输入/输出), 比从压缩 MP4 解码更准确。
"""
import argparse
import os

import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser(description="多帧hex拆为逐帧PNG")
    ap.add_argument('-i', '--input', required=True, help='hex 文件')
    ap.add_argument('-d', '--outdir', required=True, help='输出目录')
    ap.add_argument('-W', '--width', type=int, required=True)
    ap.add_argument('-H', '--height', type=int, required=True)
    ap.add_argument('--frames', type=int, required=True)
    args = ap.parse_args()

    with open(args.input) as f:
        words = np.array([int(line, 16) for line in f if line.strip()],
                         dtype=np.uint32)
    per = args.width * args.height
    os.makedirs(args.outdir, exist_ok=True)
    n = min(args.frames, words.size // per)
    for k in range(n):
        seg = words[k * per:(k + 1) * per]
        r = ((seg >> 16) & 0xFF).astype(np.uint8)
        g = ((seg >> 8) & 0xFF).astype(np.uint8)
        b = (seg & 0xFF).astype(np.uint8)
        img = np.stack([b, g, r], axis=-1).reshape(args.height, args.width, 3)
        cv2.imwrite(os.path.join(args.outdir, f"frame_{k:03d}.png"), img)
    print(f"OK: {args.outdir}  {n} 帧 PNG")


if __name__ == '__main__':
    main()
