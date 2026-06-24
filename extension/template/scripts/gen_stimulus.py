#!/usr/bin/env python3
"""gen_stimulus.py — 图像转仿真激励 hex 文件

每行一个 hex 字, 字宽/排布由 --format 决定 (见 pixfmt.py):
  RGB888 32位 {8'd0,R,G,B} / RGB24 24位 {R,G,B} / RAW8 8位灰度 / RAW16 16位。
像素顺序: 逐行, 行内从左到右。总行数 = WIDTH × HEIGHT。
"""
import argparse

import cv2

import pixfmt


def main():
    ap = argparse.ArgumentParser(description="图像转仿真激励hex")
    ap.add_argument('-i', '--input', required=True, help='输入图像 (png/bmp/jpg)')
    ap.add_argument('-o', '--output', required=True, help='输出 hex 文件')
    ap.add_argument('-f', '--format', default='RGB888', choices=pixfmt.FORMATS,
                    help='像素格式')
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

    words = pixfmt.pack(img, args.format)
    digits = pixfmt.hex_digits(args.format)
    with open(args.output, 'w') as f:
        f.writelines(f"{int(v):0{digits}x}\n" for v in words)
    print(f"OK: {args.output}  {w}x{h} {args.format}  {w * h} words")


if __name__ == '__main__':
    main()
