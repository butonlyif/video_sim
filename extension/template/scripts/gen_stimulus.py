#!/usr/bin/env python3
"""gen_stimulus.py — 图像转仿真激励 hex 文件

每行一个 32bit 十六进制字，RGB888 排列: {8'd0, R[7:0], G[7:0], B[7:0]}
像素顺序: 逐行, 行内从左到右。总行数 = WIDTH × HEIGHT。
"""
import argparse

import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser(description="图像转仿真激励hex")
    ap.add_argument('-i', '--input', required=True, help='输入图像 (png/bmp/jpg)')
    ap.add_argument('-o', '--output', required=True, help='输出 hex 文件')
    ap.add_argument('-f', '--format', default='RGB888', choices=['RGB888'],
                    help='像素格式 (当前支持 RGB888)')
    ap.add_argument('-W', '--width', type=int, help='目标宽度 (缺省用原图)')
    ap.add_argument('-H', '--height', type=int, help='目标高度 (缺省用原图)')
    args = ap.parse_args()

    img = cv2.imread(args.input, cv2.IMREAD_COLOR)  # BGR
    if img is None:
        raise SystemExit(f"ERROR: 无法读取图像 {args.input}")
    if args.width and args.height:
        img = cv2.resize(img, (args.width, args.height),
                         interpolation=cv2.INTER_AREA)
    h, w, _ = img.shape

    b = img[:, :, 0].astype(np.uint32)
    g = img[:, :, 1].astype(np.uint32)
    r = img[:, :, 2].astype(np.uint32)
    words = (r << 16) | (g << 8) | b

    with open(args.output, 'w') as f:
        f.writelines(f"{v:08x}\n" for v in words.flatten())
    print(f"OK: {args.output}  {w}x{h} {args.format}  {w * h} words")


if __name__ == '__main__':
    main()
