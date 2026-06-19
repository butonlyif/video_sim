#!/usr/bin/env python3
"""gen_video_stimulus.py — 视频(MP4等)转多帧仿真激励

抽取视频帧 → resize → 逐帧 pack 为 RGB888 → 写入 stimulus.hex (N 帧连续)。
配合 axis_video_source 的 C_STREAM=1 流式逐帧读出。
另写一份 <output>.meta.json 记录 frames/fps/width/height 供后处理使用。
"""
import argparse
import json
import os

import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser(description="视频转多帧激励hex")
    ap.add_argument('-i', '--input', required=True, help='输入视频 (mp4/avi/mov)')
    ap.add_argument('-o', '--output', required=True, help='输出 hex 文件')
    ap.add_argument('-W', '--width', type=int, required=True)
    ap.add_argument('-H', '--height', type=int, required=True)
    ap.add_argument('--max-frames', type=int, default=30,
                    help='最多抽取帧数 (iverilog 较慢, 默认 30)')
    ap.add_argument('--start', type=int, default=0, help='起始帧')
    args = ap.parse_args()

    cap = cv2.VideoCapture(args.input)
    if not cap.isOpened():
        raise SystemExit(f"ERROR: 无法打开视频 {args.input}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    for _ in range(args.start):
        cap.read()

    frames = []
    while len(frames) < args.max_frames:
        ok, img = cap.read()
        if not ok:
            break
        img = cv2.resize(img, (args.width, args.height),
                         interpolation=cv2.INTER_AREA)
        frames.append(img)
    cap.release()
    if not frames:
        raise SystemExit("ERROR: 未读到任何帧")

    with open(args.output, 'w') as f:
        for img in frames:
            b = img[:, :, 0].astype(np.uint32)
            g = img[:, :, 1].astype(np.uint32)
            r = img[:, :, 2].astype(np.uint32)
            words = ((r << 16) | (g << 8) | b).flatten()
            f.writelines(f"{v:08x}\n" for v in words)

    meta = {'frames': len(frames), 'fps': round(fps, 3),
            'width': args.width, 'height': args.height}
    with open(args.output + '.meta.json', 'w') as f:
        json.dump(meta, f)
    print(f"OK: {args.output}  {args.width}x{args.height} "
          f"{len(frames)}帧 @{fps:.1f}fps")


if __name__ == '__main__':
    main()
