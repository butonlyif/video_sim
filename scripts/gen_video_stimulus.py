#!/usr/bin/env python3
"""gen_video_stimulus.py — 将视频文件拆帧并生成 Verilog 激励文件。"""

import sys
import os
import argparse
import time

sys.path.insert(0, os.path.dirname(__file__))
from utils.console import banner, footer, h1, h2, info, success, error, kv, sub, Progress
from utils.pixel_format import get_format, image_to_pixels


def main():
    t0 = time.time()
    banner("gen_video_stimulus", version="1.0.0", desc="视频 → 逐帧激励 hex 文件")

    parser = argparse.ArgumentParser(description="视频转Verilog仿真激励")
    parser.add_argument("-i", "--input", required=True, help="输入视频路径")
    parser.add_argument("-o", "--output", default="sim/testdata/", help="输出目录（帧文件存放处）")
    parser.add_argument("-f", "--format", default="RGB888", help="像素格式")
    parser.add_argument("-w", "--width", type=int, default=1920, help="目标宽度")
    parser.add_argument("-H", "--height", type=int, default=1080, help="目标高度")
    parser.add_argument("--max-frames", type=int, default=300, help="最大处理帧数")
    args = parser.parse_args()

    h1("输入参数")
    kv("输入视频", args.input)
    kv("输出目录", args.output)
    kv("目标分辨率", f"{args.width} × {args.height}")
    kv("像素格式", args.format)
    kv("最大帧数", str(args.max_frames))

    # ---- 打开视频 ----
    h2("读取视频")
    try:
        import cv2
        cap = cv2.VideoCapture(args.input)
    except ImportError:
        error("需要安装 opencv-python")
        sys.exit(1)

    if not cap.isOpened():
        error(f"无法打开视频: {args.input}")
        sys.exit(1)

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    src_fps = cap.get(cv2.CAP_PROP_FPS)
    info(f"视频源: {total_frames} 帧, {src_fps:.1f} fps")

    frames_to_extract = min(total_frames, args.max_frames)
    info(f"将提取 {frames_to_extract} 帧")

    # ---- 逐帧处理 ----
    h2("拆帧并生成激励")
    os.makedirs(args.output, exist_ok=True)

    progress = Progress("处理帧", total=frames_to_extract)
    all_pixels = []
    frame_count = 0

    for fno in range(frames_to_extract):
        ret, frame = cap.read()
        if not ret:
            break

        if frame.shape[0] != args.height or frame.shape[1] != args.width:
            frame = cv2.resize(frame, (args.width, args.height), interpolation=cv2.INTER_LANCZOS4)

        # RGB → YUV 转换
        if args.format.upper().startswith("YUV") and len(frame.shape) == 3:
            if args.format.upper() == "YUV422":
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_YUYV)
            else:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV)

        pixels = image_to_pixels(frame, args.format)
        all_pixels.extend(pixels)
        frame_count += 1
        progress.update(1)

    cap.release()
    progress.done()
    info(f"共提取 {frame_count} 帧, {len(all_pixels):,} 像素")

    # ---- 写入 hex ----
    h2("写入激励文件")
    hex_path = os.path.join(args.output, "stimulus.hex")
    progress2 = Progress("写入 stimulus.hex", total=len(all_pixels), width=40)
    with open(hex_path, "w") as f:
        for word in all_pixels:
            f.write(f"{word:08X}\n")
            progress2.update(1)
    progress2.done()

    file_size = os.path.getsize(hex_path)
    info(f"文件大小: {file_size / 1024 / 1024:.1f} MB")
    success(f"激励文件已生成: {hex_path}")

    # 同时生成 header
    fmt_id_map = {"RAW8": 0, "RAW10": 1, "RAW12": 2, "RGB888": 3, "YUV422": 4, "YUV444": 5}
    header_path = os.path.join(args.output, "header.hex")
    with open(header_path, "w") as f:
        f.write(f"@0000  {((args.width & 0xFFFF) << 16) | (args.height & 0xFFFF):08X}\n")
        f.write(f"@0001  {fmt_id_map.get(args.format.upper(), 3):08X}\n")
        f.write(f"@0002  {frame_count:08X}\n")
        f.write(f"@0003  {int(src_fps):08X}\n")
        f.write(f"@0004  00000004\n")
    success(f"帧头文件已生成: {header_path}")

    footer(ok=True, elapsed=time.time() - t0)


if __name__ == "__main__":
    main()
