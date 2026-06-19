#!/usr/bin/env python3
"""gen_output.py — 将仿真结果 hex 文件还原为图像或视频。"""

import sys
import os
import argparse
import time

sys.path.insert(0, os.path.dirname(__file__))
from utils.console import banner, footer, h1, h2, info, success, error, kv, step, sub, Progress
from utils.pixel_format import pixels_to_image, get_format, FORMATS


def main():
    t0 = time.time()
    banner("gen_output", version="1.0.0", desc="hex 结果 → 图像/视频")

    parser = argparse.ArgumentParser(description="仿真结果hex还原为图像/视频")
    parser.add_argument("-i", "--input", required=True, help="输入 result.hex 路径")
    parser.add_argument("-o", "--output", default="output/images/result.png", help="输出图像/视频路径")
    parser.add_argument("-f", "--format", default="RGB888", help="像素格式")
    parser.add_argument("-w", "--width", type=int, default=1920, help="图像宽度")
    parser.add_argument("-H", "--height", type=int, default=1080, help="图像高度")
    parser.add_argument("--fps", type=int, default=30, help="视频帧率")
    parser.add_argument("--frames", type=int, default=1, help="总帧数（用于视频输出）")
    args = parser.parse_args()

    h1("还原参数")
    kv("输入", args.input)
    kv("输出", args.output)
    kv("分辨率", f"{args.width} × {args.height}")
    kv("像素格式", args.format)

    # ---- 读取 hex ----
    h2("读取结果数据")
    if not os.path.exists(args.input):
        error(f"文件不存在: {args.input}")
        sys.exit(1)

    pixels = []
    with open(args.input, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("//"):
                pixels.append(int(line, 16))
    info(f"读取 {len(pixels):,} 个像素字")

    pixels_per_frame = args.width * args.height
    total_frames = len(pixels) // pixels_per_frame
    if total_frames > 1:
        info(f"检测到 {total_frames} 帧数据")

    # ---- 还原为图像 ----
    h2("还原图像")
    fmt = get_format(args.format)

    # 判断输出为视频
    ext = os.path.splitext(args.output)[1].lower()
    is_video_output = ext in (".mp4", ".avi", ".mov", ".mkv")

    if is_video_output or args.frames > 1:
        frames_to_process = args.frames if args.frames > 1 else total_frames
        frames_to_process = min(frames_to_process, total_frames)
        info(f"生成视频: {frames_to_process} 帧, {args.fps} fps")

        import cv2
        import numpy as np

        sample = pixels_to_image(pixels[:pixels_per_frame], args.format, args.width, args.height)
        # 确保是 uint8
        if sample.dtype != np.uint8:
            sample = cv2.normalize(sample, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

        h, w = sample.shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        os.makedirs(os.path.dirname(args.output), exist_ok=True)
        writer = cv2.VideoWriter(args.output, fourcc, args.fps, (w, h))

        progress = Progress("合成视频帧", total=frames_to_process)
        for fno in range(frames_to_process):
            start = fno * pixels_per_frame
            end = start + pixels_per_frame
            frame_pixels = pixels[start:end]
            frame = pixels_to_image(frame_pixels, args.format, args.width, args.height)
            if frame.dtype != np.uint8:
                frame = cv2.normalize(frame, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
            writer.write(frame)
            progress.update(1)
        progress.done()
        writer.release()
    else:
        # 单帧图像
        progress = Progress("还原图像", total=1)
        img = pixels_to_image(pixels[:pixels_per_frame], args.format, args.width, args.height)
        progress.update(1)
        progress.done()

        import cv2
        import numpy as np
        if img.dtype != np.uint8:
            img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

        os.makedirs(os.path.dirname(args.output), exist_ok=True)
        cv2.imwrite(args.output, img)

    file_size = os.path.getsize(args.output)
    info(f"文件大小: {file_size / 1024 / 1024:.2f} MB")
    success(f"输出已生成: {args.output}")

    footer(ok=True, elapsed=time.time() - t0)


if __name__ == "__main__":
    main()
