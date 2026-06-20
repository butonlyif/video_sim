#!/usr/bin/env python3
"""gen_default_regcfg.py — 由 regdef.json 的 default 生成默认 regcfg.hex

平台改进 #1: "空配置 = 安全初始态" 的隐含假设只对无状态/逐点 IP 成立。
帧间类 IP(如 transpose) 必须先知道分辨率等参数才能正常结束, 空配置会挂死。
本脚本把 regdef.json 里声明的寄存器 default 真正落到 regcfg, 使其与 RTL
复位值一致(project_rules 已要求二者逐位一致), 成为 IP 的安全初始态。

输出格式与 reg_config.v / golden.read_writes 一致:
  每行一个 40bit hex 字 {addr[7:0]}{data[31:0]}, 末尾 FFFFFFFFFF 哨兵。
仅写入 access=="RW" 的寄存器(RO 寄存器无需也不应被 BFM 写入)。

用法:
  python scripts/gen_default_regcfg.py --ip <ip> [--out sim/testdata/regcfg.hex]
  python scripts/gen_default_regcfg.py --regdef rtl/<ip>/regdef.json -o regcfg.hex
"""
import argparse
import json
import os
import sys


def load_defaults(regdef_path):
    """读 regdef.json, 返回有序的 (addr, data) RW 默认值列表。"""
    with open(regdef_path) as f:
        spec = json.load(f)
    entries = []
    for reg in spec.get('registers', []):
        if reg.get('access', '').upper() != 'RW':
            continue
        addr = int(str(reg['addr']), 0) & 0xFF
        data = int(str(reg.get('default', '0x0')), 0) & 0xFFFFFFFF
        entries.append((addr, data))
    return entries


def write_regcfg(out_path, entries):
    """按 {addr[7:0]}{data[31:0]} 每行一条写出, 末尾加哨兵行。"""
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    with open(out_path, 'w') as f:
        for addr, data in entries:
            f.write(f"{addr:02x}{data:08x}\n")
        f.write("FFFFFFFFFF\n")


def main():
    ap = argparse.ArgumentParser(description="regdef.json → 默认 regcfg.hex")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--ip', help='IP 名 (从 rtl/<ip>/regdef.json 读取)')
    g.add_argument('--regdef', help='regdef.json 路径')
    ap.add_argument('-o', '--out', default='sim/testdata/regcfg.hex')
    args = ap.parse_args()

    regdef = args.regdef or os.path.join('rtl', args.ip, 'regdef.json')
    if not os.path.exists(regdef):
        # 无 regdef(如纯直通 IP): 退回空配置(仅哨兵), 保持原有行为
        write_regcfg(args.out, [])
        print(f"OK: {args.out}  (无 {regdef}, 写入空配置)")
        return

    entries = load_defaults(regdef)
    write_regcfg(args.out, entries)
    print(f"OK: {args.out}  {len(entries)} 个 RW 默认值 ← {regdef}")


if __name__ == '__main__':
    main()
