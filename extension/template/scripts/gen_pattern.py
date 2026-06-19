#!/usr/bin/env python3
"""gen_pattern.py — 测试图卡生成与故障注入

图卡类型 (--pattern): ramp 灰阶渐变 | colorbar 彩条 | graycard 灰卡
                     | checker 棋盘格 | lowcontrast 低对比度
故障注入 (可叠加, 也可作用于 --base 真实图像):
  --sigma N       高斯噪声 (降噪IP)
  --dead N        坏点注入, 坐标表写入 --table (坏点校正IP)
  --color-temp K  模拟色温偏移, 6500 为中性 (白平衡IP)
"""
import argparse

import cv2
import numpy as np


def make_pattern(name, w, h):
    img = np.zeros((h, w, 3), np.uint8)
    if name == 'ramp':
        img[:] = np.linspace(0, 255, w, dtype=np.uint8)[None, :, None]
    elif name == 'colorbar':
        colors = [(255, 255, 255), (0, 255, 255), (255, 255, 0), (0, 255, 0),
                  (255, 0, 255), (0, 0, 255), (255, 0, 0), (0, 0, 0)]  # BGR
        bw = w / len(colors)
        for i, c in enumerate(colors):
            img[:, int(i * bw):int((i + 1) * bw)] = c
    elif name == 'graycard':
        img[:] = 128
    elif name == 'checker':
        cell = max(4, w // 8)
        yy, xx = np.mgrid[0:h, 0:w]
        img[:] = np.where((((yy // cell) + (xx // cell)) % 2 == 0),
                          220, 35)[:, :, None]
    elif name == 'lowcontrast':
        x = np.linspace(0, 255, w)[None, :]
        y = np.linspace(0, 255, h)[:, None]
        base = np.stack([np.broadcast_to(x, (h, w)),
                         np.broadcast_to(y, (h, w)),
                         np.full((h, w), 128.0)], axis=-1)
        img = (base * 0.30 + 90).clip(0, 255).astype(np.uint8)
    else:
        raise SystemExit(f"ERROR: 未知图卡类型 {name}")
    return img


def main():
    ap = argparse.ArgumentParser(description="测试图卡生成与故障注入")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument('--pattern',
                     choices=['ramp', 'colorbar', 'graycard',
                              'checker', 'lowcontrast'])
    src.add_argument('--base', help='以已有图像为底图做注入')
    ap.add_argument('-o', '--output', required=True)
    ap.add_argument('-W', '--width', type=int, default=64)
    ap.add_argument('-H', '--height', type=int, default=48)
    ap.add_argument('--sigma', type=float, default=0, help='高斯噪声标准差')
    ap.add_argument('--dead', type=int, default=0, help='坏点数量')
    ap.add_argument('--table', help='坏点坐标表输出路径 (x y value 每行)')
    ap.add_argument('--color-temp', type=int, default=6500,
                    help='模拟色温K, <6500 偏暖(偏红), >6500 偏冷(偏蓝)')
    ap.add_argument('--seed', type=int, default=1, help='随机种子(可复现)')
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)

    if args.base:
        img = cv2.imread(args.base, cv2.IMREAD_COLOR)
        if img is None:
            raise SystemExit(f"ERROR: 无法读取底图 {args.base}")
        img = cv2.resize(img, (args.width, args.height),
                         interpolation=cv2.INTER_AREA)
    else:
        img = make_pattern(args.pattern, args.width, args.height)

    if args.color_temp != 6500:
        # 简化模型: 每偏离1000K, R/B 反向各变 ±8%
        f = (args.color_temp - 6500) / 1000.0
        img = img.astype(np.float64)
        img[:, :, 2] *= (1.0 - 0.08 * f)   # R: 色温低(暖)增红
        img[:, :, 0] *= (1.0 + 0.08 * f)   # B: 色温高(冷)增蓝
        img = img.clip(0, 255).astype(np.uint8)

    if args.sigma > 0:
        noise = rng.normal(0, args.sigma, img.shape)
        img = (img.astype(np.float64) + noise).clip(0, 255).astype(np.uint8)

    if args.dead > 0:
        xs = rng.integers(0, args.width, args.dead)
        ys = rng.integers(0, args.height, args.dead)
        vals = rng.choice([0, 255], args.dead)
        for x, y, v in zip(xs, ys, vals):
            img[y, x] = v
        if args.table:
            with open(args.table, 'w') as f:
                f.writelines(f"{x} {y} {v}\n"
                             for x, y, v in zip(xs, ys, vals))

    if not cv2.imwrite(args.output, img):
        raise SystemExit(f"ERROR: 无法写出 {args.output}")
    src_desc = args.pattern or args.base
    print(f"OK: {args.output}  {args.width}x{args.height}  源={src_desc}"
          f"  sigma={args.sigma} dead={args.dead} temp={args.color_temp}K")


if __name__ == '__main__':
    main()
