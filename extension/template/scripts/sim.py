#!/usr/bin/env python3
"""sim.py — 跨平台构建编排器 (取代 GNU Make 作为编排层)

纯 Python 实现全部仿真目标, 不依赖 make / Unix shell builtins
(mkdir -p / rm -f / *.v glob / diff), 故 Mac/Linux/Windows 行为完全一致。
Makefile 已退化为转发到本脚本的薄封装; 扩展与回归脚本也直接调用本脚本。

用法 (在项目根目录):
  python scripts/sim.py <target> [<target>...] [KEY=VALUE ...]

目标 (与原 Makefile 同名):
  gen_stimulus sim gen_output analyze verify check
  video_stimulus video_sim video_output video
  regression view_wave clean all

变量 (KEY=VALUE, 与原 Makefile 同名, 留空则用默认):
  IP(passthrough) WIDTH(64) HEIGHT(48) FRAMES(1) FORMAT(AUTO)
  INPUT_IMG(sim/testdata/test_input.png) INPUT_VIDEO(sim/testdata/test_input.mp4)
  FPS(30) WAVE(0) VIDEO(0)
"""
import glob
import os
import subprocess
import sys

# 始终以项目根目录为工作目录 (scripts/ 的上一级), 保证相对路径一致。
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import ip_manifest  # noqa: E402  (依赖上面的 sys.path/chdir)

PY = sys.executable  # 用当前解释器跑子脚本 (venv 内即 venv python)

DEFAULTS = {
    'IP': 'passthrough',
    'WIDTH': '64', 'HEIGHT': '48', 'FRAMES': '1', 'FORMAT': 'AUTO',
    'INPUT_IMG': 'sim/testdata/test_input.png',
    'INPUT_VIDEO': 'sim/testdata/test_input.mp4',
    'FPS': '30', 'WAVE': '0', 'VIDEO': '0',
}

V = dict(DEFAULTS)  # 运行期变量表, 命令行 KEY=VALUE 覆盖


class StepFail(Exception):
    def __init__(self, code):
        self.code = code


def sh(cmd):
    """执行一条命令 (list 形式, 不经 shell), 返回退出码。"""
    print('$ ' + ' '.join(cmd))
    sys.stdout.flush()
    return subprocess.call(cmd)


def must(code):
    if code != 0:
        raise StepFail(code)


def rm(*paths):
    for p in paths:
        if os.path.isfile(p):
            os.remove(p)


def mkdir(*paths):
    for p in paths:
        os.makedirs(p, exist_ok=True)


def rtl_all():
    return sorted(glob.glob('rtl/**/*.v', recursive=True))


def common_v():
    return sorted(glob.glob('sim/common/*.v'))


def tb_params(stream=False):
    ip = V['IP']
    p = [f'-Ptb_{ip}.C_WIDTH={V["WIDTH"]}',
         f'-Ptb_{ip}.C_HEIGHT={V["HEIGHT"]}',
         f'-Ptb_{ip}.C_FRAMES={V["FRAMES"]}']
    ow, oh = ip_manifest.out_dims(ip, int(V['WIDTH']), int(V['HEIGHT']))
    # 维度变换 IP: 仅当 OUT≠IN 时给 sink 注入输出维度 (平台改进 #2)。
    if (ow, oh) != (int(V['WIDTH']), int(V['HEIGHT'])):
        p += [f'-Ptb_{ip}.C_OUT_WIDTH={ow}', f'-Ptb_{ip}.C_OUT_HEIGHT={oh}']
    if stream:
        p.append(f'-Ptb_{ip}.C_STREAM=1')
    return p


def out_dims():
    return ip_manifest.out_dims(V['IP'], int(V['WIDTH']), int(V['HEIGHT']))


def in_fmt():
    """IP 输入格式。FORMAT 显式指定 (≠AUTO) 时覆盖一切 (控制台手动选);
    否则 AUTO: 优先 ip.json 的 in_format (导入工程自动识别), 都没有则 RGB888。"""
    if V['FORMAT'] and V['FORMAT'] != 'AUTO':
        return V['FORMAT']
    return ip_manifest.in_format(V['IP'], 'RGB888')


def out_fmt():
    """IP 输出格式。语义同 in_fmt: FORMAT 显式时覆盖, 否则 AUTO 走 ip.json/RGB888。"""
    if V['FORMAT'] and V['FORMAT'] != 'AUTO':
        return V['FORMAT']
    return ip_manifest.out_format(V['IP'], 'RGB888')


# === 目标 ===

def t_gen_stimulus():
    must(sh([PY, 'scripts/gen_stimulus.py', '-i', V['INPUT_IMG'],
             '-o', 'sim/testdata/stimulus.hex',
             '-f', in_fmt(), '-W', V['WIDTH'], '-H', V['HEIGHT']]))


def _compile_and_run(stream):
    ip = V['IP']
    mkdir('output/waves')
    rm('sim/testdata/result.hex')
    # -s tb_<ip>: 指定唯一顶层, 只 elaborate 当前 TB 的实例树。否则 iverilog 会把
    # 其它 IP 顶层(未被例化的根模块)也当顶层 elaborate, 触发它们的 initial(如某 IP
    # 的 $readmemh 加载 LUT), 造成跑 A 却报 B 的数据文件缺失 / 无关 WARNING。
    cmd = (['iverilog', '-g2012', '-s', f'tb_{ip}', '-o', f'output/{ip}.vvp']
           + tb_params(stream) + common_v() + rtl_all()
           + [f'sim/tests/tb_{ip}.v'])
    must(sh(cmd))
    plusargs = ['+WAVE'] if V['WAVE'] == '1' else []
    must(sh(['vvp', f'output/{ip}.vvp'] + plusargs))


def _gen_regcfg():
    """仿真前按当前 IP 的 regdef.json 生成 regcfg.hex，WIDTH/HEIGHT 用仿真分辨率覆盖。"""
    ip = V['IP']
    regdef = os.path.join('rtl', ip, 'regdef.json')
    if os.path.exists(regdef):
        must(sh([PY, 'scripts/gen_default_regcfg.py', '--ip', ip,
                 '-o', 'sim/testdata/regcfg.hex',
                 '-W', V['WIDTH'], '-H', V['HEIGHT']]))
    else:
        with open('sim/testdata/regcfg.hex', 'w') as f:
            f.write('FFFFFFFFFF\n')


def t_sim():
    t_gen_stimulus()
    _gen_regcfg()
    _compile_and_run(stream=(V['VIDEO'] == '1'))


def t_gen_output():
    mkdir('output/images')
    ow, oh = out_dims()
    must(sh([PY, 'scripts/gen_output.py',
             '-i', 'sim/testdata/result.hex',
             '-o', f'output/images/{V["IP"]}_output.png',
             '-f', out_fmt(), '-W', str(ow), '-H', str(oh),
             '--frames', V['FRAMES']]))


def t_analyze():
    ip = V['IP']
    mkdir('output/reports', 'output/images')
    # 基准 = stimulus.hex 还原图 (DUT 实际输入, 输入维度)
    must(sh([PY, 'scripts/gen_output.py',
             '-i', 'sim/testdata/stimulus.hex',
             '-o', f'output/images/{ip}_input.png',
             '-f', in_fmt(), '-W', V['WIDTH'], '-H', V['HEIGHT']]))
    must(sh([PY, 'scripts/analyze.py',
             '--input', f'output/images/{ip}_input.png',
             '--output', f'output/images/{ip}_output.png',
             '--report', f'output/reports/{ip}_report.json',
             '--diff', f'output/images/{ip}_diff.png',
             '--category', ip_manifest.category(ip)]))


def t_verify():
    mkdir('output/reports')
    must(sh([PY, 'scripts/verify.py', '--ip', V['IP'],
             '-W', V['WIDTH'], '-H', V['HEIGHT'],
             '--json', f'output/reports/{V["IP"]}_verify.json']))


def t_check():
    a = open('sim/testdata/stimulus.hex').read()
    b = open('sim/testdata/result.hex').read()
    if a == b:
        print('CHECK PASS: result.hex matches stimulus.hex')
    else:
        print('CHECK FAIL: result.hex differs from stimulus.hex')
        raise StepFail(1)


# === 视频模式 ===

def t_video_stimulus():
    must(sh([PY, 'scripts/gen_video_stimulus.py', '-i', V['INPUT_VIDEO'],
             '-o', 'sim/testdata/stimulus.hex',
             '-W', V['WIDTH'], '-H', V['HEIGHT'],
             '--max-frames', V['FRAMES']]))


def t_video_sim():
    t_video_stimulus()
    _gen_regcfg()
    _compile_and_run(stream=True)


def t_video_output():
    mkdir('output/video')
    must(sh([PY, 'scripts/gen_video_output.py',
             '-i', 'sim/testdata/result.hex',
             '-o', f'output/video/{V["IP"]}_output.mp4',
             '-W', V['WIDTH'], '-H', V['HEIGHT'],
             '--frames', V['FRAMES'], '--fps', V['FPS']]))


def t_video():
    t_video_sim()
    t_video_output()


def t_regression():
    must(sh([PY, 'scripts/run_regression.py']))


def t_view_wave():
    print(f'请在 Trae 中打开: output/waves/{V["IP"]}.vcd')


def t_all():
    t_sim()
    t_gen_output()
    t_analyze()


def t_clean():
    rm(f'output/{V["IP"]}.vvp',
       'sim/testdata/stimulus.hex', 'sim/testdata/result.hex')
    import shutil
    for d in ('output/images', 'output/waves'):
        if os.path.isdir(d):
            shutil.rmtree(d)


TARGETS = {
    'gen_stimulus': t_gen_stimulus, 'sim': t_sim, 'gen_output': t_gen_output,
    'analyze': t_analyze, 'verify': t_verify, 'check': t_check,
    'video_stimulus': t_video_stimulus, 'video_sim': t_video_sim,
    'video_output': t_video_output, 'video': t_video,
    'regression': t_regression, 'view_wave': t_view_wave,
    'clean': t_clean, 'all': t_all,
}


def main():
    targets = []
    for arg in sys.argv[1:]:
        if '=' in arg:
            key, val = arg.split('=', 1)
            val = val.strip().strip('"').strip("'")  # 剥离首尾引号 (跨平台兼容)
            if key in V and val != '':   # 留空 → 保留默认
                V[key] = val
        else:
            targets.append(arg)
    if not targets:
        print(__doc__)
        sys.exit(2)
    for t in targets:
        if t not in TARGETS:
            print(f'未知目标: {t}', file=sys.stderr)
            sys.exit(2)
    try:
        for t in targets:
            TARGETS[t]()
    except StepFail as e:
        sys.exit(e.code)


if __name__ == '__main__':
    main()
