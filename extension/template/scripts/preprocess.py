#!/usr/bin/env python3
"""preprocess.py — 图像/视频预处理模块 (可插拔)

对图像或视频施加预处理后输出同类型文件。内置算子: 高斯噪声 / 椒盐坏点 / 模糊 /
降采样退化。支持自定义算子插件: --custom scripts/preprocess_custom.py
(其中定义 process(frame, idx, rng) -> frame, 由 Trae AI 按需求填写)。

用法:
  # 图像加噪声
  python scripts/preprocess.py -i in.png -o out.png --noise 15
  # 视频加坏点 + 噪声
  python scripts/preprocess.py -i in.mp4 -o out.mp4 --noise 10 --dead 200
  # 自定义 (AI 生成的算子)
  python scripts/preprocess.py -i in.mp4 -o out.mp4 --custom scripts/preprocess_custom.py
"""
import argparse
import importlib.util
import os

import cv2
import numpy as np


def build_ops(args, rng):
    """返回算子列表, 每个算子 (frame, idx) -> frame。"""
    ops = []
    if args.noise > 0:
        sigma = args.noise
        ops.append(lambda f, i: np.clip(
            f.astype(np.float64) + rng.normal(0, sigma, f.shape),
            0, 255).astype(np.uint8))
    if args.dead > 0:
        n = args.dead
        def dead_op(f, i):
            h, w = f.shape[:2]
            xs = rng.integers(0, w, n); ys = rng.integers(0, h, n)
            vals = rng.choice([0, 255], n)
            for x, y, v in zip(xs, ys, vals):
                f[y, x] = v
            return f
        ops.append(dead_op)
    if args.blur > 0:
        k = args.blur | 1   # 奇数核
        ops.append(lambda f, i: cv2.GaussianBlur(f, (k, k), 0))
    if args.custom:
        spec = importlib.util.spec_from_file_location('ppcustom', args.custom)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if not hasattr(mod, 'process'):
            raise SystemExit(f"ERROR: {args.custom} 缺少 process(frame, idx, rng) 函数")
        ops.append(lambda f, i: mod.process(f, i, rng))
    return ops


def apply_ops(frame, idx, ops):
    for op in ops:
        frame = op(frame, idx)
    return frame


def main():
    ap = argparse.ArgumentParser(description="图像/视频预处理")
    ap.add_argument('-i', '--input', required=True)
    ap.add_argument('-o', '--output', required=True)
    ap.add_argument('--noise', type=float, default=0, help='高斯噪声 sigma')
    ap.add_argument('--dead', type=int, default=0, help='坏点数/帧')
    ap.add_argument('--blur', type=int, default=0, help='高斯模糊核大小')
    ap.add_argument('--custom', help='自定义算子 .py (含 process(frame,idx,rng))')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--max-frames', type=int, default=300)
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    ops = build_ops(args, rng)
    if not ops:
        raise SystemExit("ERROR: 未指定任何预处理算子")

    ext = os.path.splitext(args.input)[1].lower()
    is_video = ext in ('.mp4', '.avi', '.mov', '.mkv')

    if is_video:
        cap = cv2.VideoCapture(args.input)
        if not cap.isOpened():
            raise SystemExit(f"ERROR: 无法打开 {args.input}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        vw = cv2.VideoWriter(args.output, cv2.VideoWriter_fourcc(*'mp4v'),
                             fps, (w, h))
        n = 0
        while n < args.max_frames:
            ok, fr = cap.read()
            if not ok:
                break
            vw.write(apply_ops(fr, n, ops))
            n += 1
        cap.release(); vw.release()
        print(f"OK: {args.output}  视频 {w}x{h} {n}帧 预处理完成")
    else:
        img = cv2.imread(args.input, cv2.IMREAD_COLOR)
        if img is None:
            raise SystemExit(f"ERROR: 无法读取 {args.input}")
        out = apply_ops(img, 0, ops)
        if not cv2.imwrite(args.output, out):
            raise SystemExit(f"ERROR: 无法写出 {args.output}")
        print(f"OK: {args.output}  图像预处理完成")


if __name__ == '__main__':
    main()
