#!/usr/bin/env python3
"""gen_output.py — 仿真结果 hex 还原为图像

读取 result.hex (每行一个 hex 字, 排布由 --format 决定, 见 pixfmt.py),
重塑为 H×W×3 图像并保存。单通道格式 (RAW8/RAW16) 复制到三通道显示。
"""
import argparse

import cv2
import numpy as np

import pixfmt


def main():
    ap = argparse.ArgumentParser(description="仿真结果hex转图像")
    ap.add_argument('-i', '--input', required=True, help='输入 hex 文件')
    ap.add_argument('-o', '--output', required=True, help='输出图像 (png/bmp)')
    ap.add_argument('-f', '--format', default='RGB888', choices=pixfmt.FORMATS)
    ap.add_argument('-W', '--width', type=int, required=True)
    ap.add_argument('-H', '--height', type=int, required=True)
    ap.add_argument('--frames', type=int, default=1, help='hex 中总帧数')
    ap.add_argument('--frame', type=int, default=-1,
                    help='提取第几帧(0起), 默认最后一帧')
    args = ap.parse_args()

    with open(args.input) as f:
        words = np.array([int(line, 16) for line in f if line.strip()],
                         dtype=np.uint32)

    per_frame = args.width * args.height
    expect = per_frame * args.frames
    if words.size != expect:
        raise SystemExit(
            f"ERROR: 像素数不匹配: hex含 {words.size} 字, "
            f"期望 {args.width}x{args.height}x{args.frames}帧 = {expect}")
    k = args.frame if args.frame >= 0 else args.frames - 1
    if k >= args.frames:
        raise SystemExit(f"ERROR: 帧号 {k} 超出范围 (共 {args.frames} 帧)")
    words = words[k * per_frame:(k + 1) * per_frame]

    img = pixfmt.unpack(words, args.format, args.height, args.width)

    if not cv2.imwrite(args.output, img):
        raise SystemExit(f"ERROR: 无法写出图像 {args.output}")
    print(f"OK: {args.output}  {args.width}x{args.height} {args.format}")


if __name__ == '__main__':
    main()
