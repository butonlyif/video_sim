#!/usr/bin/env python3
"""gen_header.py — 生成帧头信息 hex 文件，供 Verilog Source BFM 读取。"""

import sys
import os
import argparse
import time

sys.path.insert(0, os.path.dirname(__file__))
from utils.console import banner, footer, h1, info, success, kv, table


def main():
    t0 = time.time()
    banner("gen_header", version="1.0.0", desc="生成帧头信息文件")

    parser = argparse.ArgumentParser(description="生成帧头信息 hex 文件")
    parser.add_argument("-o", "--output", default="sim/testdata/header.hex", help="输出文件路径")
    parser.add_argument("-w", "--width", type=int, default=1920, help="图像宽度")
    parser.add_argument("-H", "--height", type=int, default=1080, help="图像高度")
    parser.add_argument("-f", "--format", default="RGB888", help="像素格式")
    parser.add_argument("-n", "--frames", type=int, default=1, help="总帧数")
    parser.add_argument("--fps", type=int, default=30, help="帧率")
    parser.add_argument("--parallel", type=int, default=4, help="并行度 C_PARALLEL")
    args = parser.parse_args()

    fmt_id_map = {"RAW8": 0, "RAW10": 1, "RAW12": 2, "RGB888": 3, "YUV422": 4, "YUV444": 5}
    fmt_id = fmt_id_map.get(args.format.upper(), -1)

    h1("帧头参数")
    kv("输出文件", args.output)
    kv("分辨率", f"{args.width} × {args.height}")
    kv("像素格式", f"{args.format} (ID={fmt_id})")
    kv("帧数", str(args.frames))
    kv("帧率", f"{args.fps} fps")
    kv("并行度", str(args.parallel))

    # 生成 header.hex 内容（Verilog $readmemh 格式）
    lines = [
        f"@0000  {((args.width & 0xFFFF) << 16) | (args.height & 0xFFFF):08X}  // IMG_WIDTH | IMG_HEIGHT",
        f"@0001  {fmt_id:08X}  // 像素格式ID",
        f"@0002  {args.frames:08X}  // 总帧数",
        f"@0003  {args.fps:08X}  // 帧率",
        f"@0004  {args.parallel:08X}  // C_PARALLEL",
    ]

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        f.write("\n".join(lines) + "\n")

    success(f"帧头文件已生成: {args.output} ({len(lines)} 条记录)")
    footer(ok=True, elapsed=time.time() - t0)


if __name__ == "__main__":
    main()
