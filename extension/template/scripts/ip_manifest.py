#!/usr/bin/env python3
"""ip_manifest.py — 读取 rtl/<ip>/ip.json 元数据(平台改进 #2/#3)

可选的 IP 清单, 让工具链理解 "输出维度 = f(输入维度)" 与 IP 分类:

  rtl/<ip>/ip.json
  {
    "category": "pointwise | geometric | interframe",
    "dims": { "out_w": "in_h", "out_h": "in_w" }   // 表达式, 变量 in_w/in_h
  }

缺省(无清单或字段缺失)= 逐点恒等: category=pointwise, out_w=in_w, out_h=in_h,
故现有 IP 完全不受影响。dims 表达式在仅含 {in_w, in_h} 的受限命名空间下求值。

作为库使用:
  from ip_manifest import category, out_dims
  out_w, out_h = out_dims('transpose', 64, 48)   # -> (48, 64)

作为命令行使用(供 Makefile / shell 读取):
  python scripts/ip_manifest.py --ip transpose --in-w 64 --in-h 48 --get out_w
  python scripts/ip_manifest.py --ip transpose --get category
"""
import argparse
import json
import os

CATEGORIES = ('pointwise', 'geometric', 'interframe')


def _manifest_path(ip):
    return os.path.join('rtl', ip, 'ip.json')


def load(ip):
    """读 rtl/<ip>/ip.json, 不存在或解析失败返回空 dict。"""
    path = _manifest_path(ip)
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (ValueError, OSError):
        return {}


def category(ip):
    """返回 IP 分类, 缺省 'pointwise'。"""
    c = load(ip).get('category', 'pointwise')
    return c if c in CATEGORIES else 'pointwise'


def _eval_dim(expr, in_w, in_h):
    """在仅含 in_w/in_h 的受限命名空间求值, 整数结果。"""
    if isinstance(expr, int):
        return expr
    return int(eval(str(expr), {'__builtins__': {}}, {'in_w': in_w, 'in_h': in_h}))


def out_dims(ip, in_w, in_h):
    """由 dims 表达式算输出维度, 缺省恒等 (in_w, in_h)。"""
    dims = load(ip).get('dims', {})
    out_w = _eval_dim(dims.get('out_w', 'in_w'), in_w, in_h)
    out_h = _eval_dim(dims.get('out_h', 'in_h'), in_w, in_h)
    return out_w, out_h


def main():
    ap = argparse.ArgumentParser(description="读取 IP 清单元数据")
    ap.add_argument('--ip', required=True)
    ap.add_argument('--in-w', type=int, default=0)
    ap.add_argument('--in-h', type=int, default=0)
    ap.add_argument('--get', required=True,
                    choices=['out_w', 'out_h', 'category'])
    args = ap.parse_args()

    if args.get == 'category':
        print(category(args.ip))
    else:
        ow, oh = out_dims(args.ip, args.in_w, args.in_h)
        print(ow if args.get == 'out_w' else oh)


if __name__ == '__main__':
    main()
