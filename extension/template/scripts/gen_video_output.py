#!/usr/bin/env python3
"""gen_video_output.py — 多帧结果 hex 合成为视频(MP4)

读取 result.hex (N 帧 RGB888), 逐帧重塑, 用 OpenCV VideoWriter 合成视频。
"""
import argparse

import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser(description="多帧结果hex转视频")
    ap.add_argument('-i', '--input', required=True, help='结果 hex 文件')
    ap.add_argument('-o', '--output', required=True, help='输出视频 (mp4)')
    ap.add_argument('-W', '--width', type=int, required=True)
    ap.add_argument('-H', '--height', type=int, required=True)
    ap.add_argument('--frames', type=int, required=True)
    ap.add_argument('--fps', type=float, default=30.0)
    args = ap.parse_args()

    with open(args.input) as f:
        words = np.array([int(line, 16) for line in f if line.strip()],
                         dtype=np.uint32)

    per_frame = args.width * args.height
    expect = per_frame * args.frames
    if words.size < expect:
        raise SystemExit(f"ERROR: 像素数不足: hex {words.size}, "
                         f"期望 {expect} ({args.frames}帧)")

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    vw = cv2.VideoWriter(args.output, fourcc, args.fps,
                         (args.width, args.height))
    if not vw.isOpened():
        raise SystemExit(f"ERROR: 无法创建视频 {args.output}")

    for k in range(args.frames):
        seg = words[k * per_frame:(k + 1) * per_frame]
        r = ((seg >> 16) & 0xFF).astype(np.uint8)
        g = ((seg >> 8) & 0xFF).astype(np.uint8)
        b = (seg & 0xFF).astype(np.uint8)
        img = np.stack([b, g, r], axis=-1).reshape(args.height, args.width, 3)
        vw.write(img)
    vw.release()
    print(f"OK: {args.output}  {args.width}x{args.height} "
          f"{args.frames}帧 @{args.fps:.1f}fps")


if __name__ == '__main__':
    main()
