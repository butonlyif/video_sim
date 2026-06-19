#!/usr/bin/env python3
"""gen_stimulus.py — 将图像文件转换为 Verilog 仿真激励 hex 文件。"""

import sys
import os
import argparse
import time

sys.path.insert(0, os.path.dirname(__file__))
from utils.console import banner, footer, h1, h2, info, success, warn, error, kv, step, sub, Progress
from utils.pixel_format import get_format, image_to_pixels, FORMATS


def main():
    t0 = time.time()
    banner("gen_stimulus", version="1.0.0", desc="图像 → 像素激励 hex 文件")

    parser = argparse.ArgumentParser(description="图像转Verilog仿真激励")
    parser.add_argument("-i", "--input", required=True, help="输入图像路径")
    parser.add_argument("-o", "--output", default="sim/testdata/stimulus.hex", help="输出 hex 路径")
    parser.add_argument("-f", "--format", default="RGB888", help="像素格式")
    parser.add_argument("-w", "--width", type=int, default=1920, help="目标宽度")
    parser.add_argument("-H", "--height", type=int, default=1080, help="目标高度")
    parser.add_argument("--keep-alpha", action="store_true", help="保留 alpha 通道")
    args = parser.parse_args()

    h1("输入参数")
    kv("输入图像", args.input)
    kv("输出文件", args.output)
    kv("目标分辨率", f"{args.width} × {args.height}")
    kv("像素格式", args.format)

    # ---- 读取图像 ----
    h2("读取图像")
    try:
        import cv2
        img = cv2.imread(args.input, cv2.IMREAD_UNCHANGED)
    except ImportError:
        from PIL import Image
        import numpy as np
        pil_img = Image.open(args.input)
        img = np.array(pil_img)

    if img is None:
        error(f"无法读取图像: {args.input}")
        sys.exit(1)

    info(f"原始尺寸: {img.shape[1]} × {img.shape[0]}")
    if len(img.shape) == 3 and img.shape[2] == 4 and not args.keep_alpha:
        warn("alpha 通道已丢弃 (使用 --keep-alpha 保留)")
        img = img[:, :, :3]
    elif len(img.shape) == 3 and img.shape[2] == 4 and args.keep_alpha:
        warn("alpha 通道已保留（注意：tdata 格式不含 alpha）")

    # ---- 缩放 ----
    if img.shape[0] != args.height or img.shape[1] != args.width:
        info(f"缩放至 {args.width} × {args.height}")
        import cv2
        img = cv2.resize(img, (args.width, args.height), interpolation=cv2.INTER_LANCZOS4)

    # ---- 格式变换 ----
    fmt = get_format(args.format)
    h2("像素格式转换")
    info(f"目标格式: {fmt['name']} (每像素 {fmt['bits']} bits, tdata={fmt['tdata_bits']} bits)")

    # RGB → YUV 转换（如果需要）
    if args.format.upper().startswith("YUV") and len(img.shape) == 3 and img.shape[2] >= 3:
        if args.format.upper() == "YUV422":
            import cv2
            img = cv2.cvtColor(img, cv2.COLOR_BGR2YUV_YUYV)
        else:
            import cv2
            img = cv2.cvtColor(img, cv2.COLOR_BGR2YUV)

    # ---- 生成像素 ----
    h2("生成激励数据")
    total_pixels = args.width * args.height
    info(f"总像素数: {total_pixels:,}")

    pixels = image_to_pixels(img, args.format)

    # ---- 写入 hex ----
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    progress = Progress("写入 stimulus.hex", total=len(pixels))
    with open(args.output, "w") as f:
        for word in pixels:
            f.write(f"{word:08X}\n")
            progress.update(1)
    progress.done()

    file_size = os.path.getsize(args.output)
    info(f"文件大小: {file_size / 1024 / 1024:.1f} MB")
    success(f"激励文件已生成: {args.output}")

    footer(ok=True, elapsed=time.time() - t0)


if __name__ == "__main__":
    main()
