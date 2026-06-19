#!/usr/bin/env python3
"""compare.py — result.hex 与 expected.hex 逐字比对

逐像素比较两份 hex，按容差判定 PASS/FAIL；输出首个失配位置、失配统计。
返回非零退出码表示 FAIL（供 Makefile / CI 直接使用）。

用法:
  python scripts/compare.py \
      --result   sim/testdata/result.hex \
      --expected sim/testdata/expected.hex \
      -W 64 -H 48 [--tolerance 0] [--max-mismatch-frac 0.0] [--json out.json]
"""
import argparse
import json
import sys


def load(path):
    with open(path) as f:
        return [int(line, 16) for line in f if line.strip()]


def split(v):
    return ((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF)


def main():
    ap = argparse.ArgumentParser(description="result vs expected 比对")
    ap.add_argument('--result', required=True)
    ap.add_argument('--expected', required=True)
    ap.add_argument('-W', '--width', type=int, required=True)
    ap.add_argument('-H', '--height', type=int, required=True)
    ap.add_argument('--tolerance', type=int, default=0,
                    help='每通道允许的最大绝对差 (LSB)')
    ap.add_argument('--max-mismatch-frac', type=float, default=0.0,
                    help='允许超出容差的像素比例上限')
    ap.add_argument('--json', help='比对报告 JSON 输出路径')
    args = ap.parse_args()

    res, exp = load(args.result), load(args.expected)
    n = min(len(res), len(exp))
    per_frame = args.width * args.height

    mismatch = 0
    max_diff = 0
    first = None
    for i in range(n):
        rr = split(res[i]); ee = split(exp[i])
        diff = max(abs(a - b) for a, b in zip(rr, ee))
        if diff > max_diff:
            max_diff = diff
        if diff > args.tolerance:
            mismatch += 1
            if first is None:
                fr, idx = divmod(i, per_frame)
                y, x = divmod(idx, args.width)
                first = {'index': i, 'frame': fr, 'x': x, 'y': y,
                         'result': f"{res[i]:06x}", 'expected': f"{exp[i]:06x}"}

    len_ok = (len(res) == len(exp))
    frac = mismatch / n if n else 1.0
    passed = len_ok and (frac <= args.max_mismatch_frac)

    report = {
        'passed': passed,
        'total': n,
        'length_match': len_ok,
        'result_len': len(res), 'expected_len': len(exp),
        'tolerance': args.tolerance,
        'mismatch': mismatch,
        'mismatch_frac': round(frac, 5),
        'max_mismatch_frac': args.max_mismatch_frac,
        'max_diff': max_diff,
        'first_mismatch': first,
    }

    if args.json:
        with open(args.json, 'w') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    tag = 'PASS' if passed else 'FAIL'
    extra = '' if len_ok else f" 长度不符(res={len(res)} exp={len(exp)})"
    fm = '' if not first else f" 首失配@帧{first['frame']}({first['x']},{first['y']})"
    print(f"{tag}: 金标准比对 失配 {mismatch}/{n} "
          f"({frac*100:.2f}%, 容差±{args.tolerance}, 最大差{max_diff}){extra}{fm}")
    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
