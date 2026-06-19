#!/usr/bin/env python3
"""verify.py — 金标准验证编排器

按 IP 的内置配置（帧数/容差/容许失配比例），生成期望输出并比对仿真结果，
输出 PASS/FAIL。是控制台与回归调用的统一入口。

用法（stimulus 与 result 须已由 make sim 生成）:
  python scripts/verify.py --ip <ip> -W 64 -H 48 \
      [--stimulus ...] [--result ...] [--regcfg ...] [--json ...]
"""
import argparse
import os
import subprocess
import sys
import tempfile

import golden


def main():
    ap = argparse.ArgumentParser(description="金标准验证编排")
    ap.add_argument('--ip', required=True, choices=sorted(golden.CONFIG))
    ap.add_argument('-W', '--width', type=int, required=True)
    ap.add_argument('-H', '--height', type=int, required=True)
    ap.add_argument('--frames', type=int, default=None,
                    help='覆盖 IP 默认帧数')
    ap.add_argument('--stimulus', default='sim/testdata/stimulus.hex')
    ap.add_argument('--result', default='sim/testdata/result.hex')
    ap.add_argument('--regcfg', default='sim/testdata/regcfg.hex')
    ap.add_argument('--expected', default='sim/testdata/expected.hex')
    ap.add_argument('--json', default=None)
    args = ap.parse_args()

    cfg = golden.CONFIG[args.ip]
    frames = args.frames if args.frames is not None else cfg['frames']

    # 1) 金标准模型 → expected.hex
    frame = golden.read_frame(args.stimulus, args.width, args.height)
    writes = golden.read_writes(args.regcfg) if os.path.exists(args.regcfg) else []
    outs = golden.generate(args.ip, frame, frames, writes)
    golden.write_frames(args.expected, outs)

    # 2) 调 compare.py（独立进程，复用其退出码语义）
    here = os.path.dirname(os.path.abspath(__file__))
    cmd = [sys.executable, os.path.join(here, 'compare.py'),
           '--result', args.result, '--expected', args.expected,
           '-W', str(args.width), '-H', str(args.height),
           '--tolerance', str(cfg['tol']),
           '--max-mismatch-frac', str(cfg['frac'])]
    if args.json:
        cmd += ['--json', args.json]
    sys.exit(subprocess.call(cmd))


if __name__ == '__main__':
    main()
