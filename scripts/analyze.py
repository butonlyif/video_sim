#!/usr/bin/env python3
"""analyze.py — 图像质量分析总入口。

用法:
  python scripts/analyze.py --input input.png --output output.png --all
  python scripts/analyze.py --input img.png --metric sharpness
"""

import sys
import os
import json
import argparse
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from utils.console import (
    banner, footer, h1, h2, info, success, warn, error,
    kv, step, sub, divider, table, Progress, green, red, yellow, bold,
)
from analyzers import sharpness, white_balance, histogram, psnr, gamma


AVAILABLE_METRICS = {
    "sharpness":     ("锐度分析",     sharpness),
    "white_balance": ("白平衡分析",   white_balance),
    "histogram":     ("直方图分析",   histogram),
    "psnr":          ("PSNR",       psnr),
    "gamma":         ("Gamma 曲线",  gamma),
}


def main():
    t0 = time.time()
    banner("analyze", version="1.0.0", desc="图像质量分析工具")

    parser = argparse.ArgumentParser(description="图像质量分析")
    parser.add_argument("--input", required=True, help="输入原图路径")
    parser.add_argument("--output", default=None, help="IP 输出图路径（PSNR/Gamma 必填）")
    parser.add_argument("--all", action="store_true", help="运行全部分析项")
    parser.add_argument("--metric", default=None, help=f"单项分析: {', '.join(AVAILABLE_METRICS.keys())}")
    parser.add_argument("--report", default=None, help="报告输出 JSON 路径")
    parser.add_argument("--roi", default=None, help="分析区域 x,y,w,h（暂未使用）")
    args = parser.parse_args()

    # ---- 确定要跑的指标 ----
    if args.all:
        metrics_to_run = list(AVAILABLE_METRICS.keys())
    elif args.metric:
        if args.metric not in AVAILABLE_METRICS:
            error(f"不支持的指标: {args.metric}。可选: {list(AVAILABLE_METRICS.keys())}")
            sys.exit(1)
        metrics_to_run = [args.metric]
    else:
        metrics_to_run = ["sharpness", "white_balance", "histogram"]

    h1("分析配置")
    kv("输入图像", args.input)
    kv("输出图像", args.output or "(未提供)")
    kv("分析项", ", ".join(metrics_to_run))

    # ---- 加载图像 ----
    h2("加载图像")
    import cv2
    input_img = cv2.imread(args.input)
    if input_img is None:
        error(f"无法读取: {args.input}")
        sys.exit(1)
    info(f"输入: {input_img.shape[1]} × {input_img.shape[0]}")

    output_img = None
    if args.output and os.path.exists(args.output):
        output_img = cv2.imread(args.output)
        if output_img is None:
            warn(f"无法读取输出图: {args.output}，对比类分析将跳过")
        else:
            info(f"输出: {output_img.shape[1]} × {output_img.shape[0]}")

            if output_img.shape[:2] != input_img.shape[:2]:
                warn(f"尺寸不一致: 输入 {input_img.shape[:2]}, 输出 {output_img.shape[:2]}，将缩放对齐")
                output_img = cv2.resize(output_img, (input_img.shape[1], input_img.shape[0]))
    elif args.metric in ("psnr", "gamma") and not args.output:
        warn(f"{args.metric} 需要 --output 参数提供对比图")
        info("将仅展示无需对比的分析项")

    # ---- 逐项分析 ----
    results = {}
    progress = Progress("分析进度", total=len(metrics_to_run))

    for metric_name in metrics_to_run:
        label, module = AVAILABLE_METRICS[metric_name]

        if metric_name in ("psnr", "gamma") and output_img is None:
            results[metric_name] = {"skipped": "需要 --output 对比图"}
            progress.update(1)
            continue

        try:
            result = module.analyze(input_img, output_img)
            results[metric_name] = result
        except Exception as e:
            results[metric_name] = {"error": str(e)}
        progress.update(1)
    progress.done()

    # ---- 打印结果 ----
    h2("分析结果")

    for metric_name, result in results.items():
        if "error" in result:
            warn(f"{AVAILABLE_METRICS[metric_name][0]}: {result['error']}")
        elif "skipped" in result:
            info(f"{AVAILABLE_METRICS[metric_name][0]}: {result['skipped']}")

    # 锐度
    if "sharpness" in results and "error" not in results["sharpness"]:
        r = results["sharpness"]
        sub(f"锐度: Laplacian={r['laplacian_variance']}, Tenengrad={r['tenengrad']:.0f}")
        grade_color = green if r['grade'] in ("优秀", "极佳") else (yellow if r['grade'] == "良好" else red)
        divider()
        kv("锐度等级", grade_color(r['grade']))

    # 白平衡
    if "white_balance" in results and "error" not in results["white_balance"]:
        r = results["white_balance"]
        sub(f"增益: R={r['r_gain']} G={r['g_gain']} B={r['b_gain']}")
        divider()
        kv("色温倾向", r['bias'])

    # 直方图
    if "histogram" in results and "error" not in results["histogram"]:
        r = results["histogram"]
        if "shift" in r:
            kv("亮度变化", r['shift'])

    # PSNR
    if "psnr" in results and "error" not in results["psnr"]:
        r = results["psnr"]
        p_color = green if r['overall'] > 40 else (yellow if r['overall'] > 30 else red)
        divider()
        kv("PSNR", p_color(f"{r['overall']} dB"))
        kv("PSNR 等级", r['grade'])

    # Gamma
    if "gamma" in results and "error" not in results["gamma"]:
        r = results["gamma"]
        divider()
        kv("实测 Gamma", f"{r.get('measured', 'N/A')}")
        kv("目标 Gamma", f"{r.get('target', 'N/A')}")
        kv("偏差", f"{r.get('delta', 'N/A')}")
        kv("Gamma 等级", r.get("grade", "N/A"))

    divider()

    # ---- 生成报告 ----
    report_path = args.report
    if not report_path and args.all:
        os.makedirs("output/reports", exist_ok=True)
        report_path = f"output/reports/analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    if report_path:
        report = {
            "input_file": args.input,
            "output_file": args.output,
            "resolution": f"{input_img.shape[1]}x{input_img.shape[0]}",
            "timestamp": datetime.now().isoformat(),
            "metrics": results,
        }
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        success(f"报告已保存: {report_path}")

    footer(ok=True, elapsed=time.time() - t0)


if __name__ == "__main__":
    main()
