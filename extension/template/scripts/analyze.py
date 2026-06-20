#!/usr/bin/env python3
"""analyze.py — 图像质量分析 (彩色终端输出 + 控制台面板 JSON)

同时满足两种消费方:
  1. 终端/输出面板: 用 utils.console 漂亮打印 (管道时自动关色)
  2. 仿真控制台 Webview: 输出 input/output 成对 + 256-bin 直方图 + 差异图

用法:
  python scripts/analyze.py --input in.png --output out.png \
      --report output/reports/ip_report.json --diff output/images/ip_diff.png
"""
import argparse
import json
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from utils.console import (banner, footer, h1, h2, kv, warn, success,
                           divider, green, yellow, red)
from analyzers import sharpness, white_balance, psnr as psnr_mod


def hist256(img):
    return {ch: cv2.calcHist([img], [i], None, [256], [0, 256])
            .flatten().astype(int).tolist()
            for i, ch in enumerate(('b', 'g', 'r'))}


def error_exit(msg):
    warn(msg)
    print(f"ERROR: {msg}")
    sys.exit(1)


def main():
    t0 = time.time()
    banner("analyze", version="2.0.0", desc="图像质量分析")

    ap = argparse.ArgumentParser(description="图像质量分析")
    ap.add_argument('--input', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--report', required=True)
    ap.add_argument('--diff')
    ap.add_argument('--diff-gain', type=int, default=8)
    ap.add_argument('--category', default='pointwise',
                    choices=['pointwise', 'geometric', 'interframe'],
                    help='IP 分类(平台改进 #3): 非 pointwise 跳过逐像素对齐指标')
    args = ap.parse_args()

    h1("加载图像")
    img_in = cv2.imread(args.input, cv2.IMREAD_COLOR)
    img_out = cv2.imread(args.output, cv2.IMREAD_COLOR)
    if img_in is None:
        error_exit(f"无法读取输入 {args.input}")
    if img_out is None:
        error_exit(f"无法读取输出 {args.output}")
    # 逐像素对齐指标(PSNR/差异图)只对 pointwise(输入输出同尺寸同语义)有意义;
    # 几何/帧间类 IP 强行对齐会产生误导性指标, 正确入口是 verify 金标准(平台改进 #3)。
    aligned = (args.category == 'pointwise')
    if aligned and img_in.shape != img_out.shape:
        error_exit(f"尺寸不一致: {img_in.shape} vs {img_out.shape}")
    h, w, _ = img_out.shape
    kv("输入", args.input)
    kv("输出", args.output)
    kv("分类", args.category)
    kv("分辨率", f"{w} × {h}"
       + ("" if aligned else f"  (输入 {img_in.shape[1]} × {img_in.shape[0]})"))

    identical = aligned and bool(np.array_equal(img_in, img_out))

    # 单图分析 (analyzers 模块: analyze(img) 测量该图, 不要求对齐)
    sh_in, sh_out = sharpness.analyze(img_in), sharpness.analyze(img_out)
    wb_in, wb_out = white_balance.analyze(img_in), white_balance.analyze(img_out)
    # 逐像素对齐指标: 仅 pointwise 计算
    pr = psnr_mod.analyze(img_in, img_out) if aligned else {}
    ch = pr.get('channels', {})

    report = {
        'input_file': args.input, 'output_file': args.output,
        'category': args.category, 'aligned_metrics': aligned,
        'resolution': f"{w}x{h}", 'identical': identical,
        'psnr': None if not aligned else {
            'overall': None if identical else pr.get('overall'),
            'channel_r': None if identical else ch.get('R'),
            'channel_g': None if identical else ch.get('G'),
            'channel_b': None if identical else ch.get('B'),
            'grade': pr.get('grade'),
        },
        'sharpness': {'input': sh_in, 'output': sh_out},
        'white_balance': {'input': wb_in, 'output': wb_out},
        'histograms': {'input': hist256(img_in), 'output': hist256(img_out)},
    }

    # 差异热力图: 仅 pointwise (需逐像素对齐)
    if args.diff and aligned:
        d = cv2.absdiff(img_in, img_out).max(axis=2)
        d = np.clip(d.astype(np.int32) * args.diff_gain, 0, 255).astype(np.uint8)
        cv2.imwrite(args.diff, cv2.applyColorMap(d, cv2.COLORMAP_JET))

    # 漂亮打印
    h2("分析结果")
    sg = (lambda g: green(g) if g in ('优秀', '极佳') else
          (yellow(g) if g == '良好' else red(g)))
    kv("锐度(Laplacian)", f"{sh_in['laplacian_variance']} -> "
       f"{sh_out['laplacian_variance']}  [{sg(sh_out['grade'])}]")
    kv("白平衡增益(出)", f"R {wb_out['r_gain']} / G {wb_out['g_gain']} / "
       f"B {wb_out['b_gain']}  ({wb_out.get('bias', '')})")
    if not aligned:
        kv("PSNR/差异", yellow(f"不适用({args.category}类) — 请用 verify 金标准比对"))
    elif identical:
        kv("PSNR", green("inf (输出与输入完全一致)"))
    else:
        p = pr.get('overall', 0)
        pc = green if p > 40 else (yellow if p > 30 else red)
        kv("PSNR", pc(f"{p} dB  [{pr.get('grade', '')}]"))
    divider()

    os.makedirs(os.path.dirname(args.report) or '.', exist_ok=True)
    with open(args.report, 'w') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    success(f"报告: {args.report}"
            + (f"  差异图: {args.diff}" if args.diff else ""))
    footer(ok=True, elapsed=time.time() - t0)


if __name__ == '__main__':
    main()
