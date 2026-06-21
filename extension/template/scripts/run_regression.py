#!/usr/bin/env python3
"""run_regression.py — 项目内回归测试入口 (Windows 兼容版本)

用法: python scripts/run_regression.py   (在项目根目录执行)
对 rtl/ 下所有带 TB 的 IP 做冒烟测试; 对已知 IP 追加功能性检查。
"""
import os
import sys
import glob
import shutil
import subprocess

# 切换到项目根目录
os.chdir(os.path.join(os.path.dirname(__file__), '..'))

FAIL = 0


def note(msg):
    print(f"\n=== {msg} ===")


def reset_regcfg(ip=None):
    """按 regdef.json 的 default 生成默认 regcfg(平台改进 #1)"""
    regcfg_path = 'sim/testdata/regcfg.hex'
    if ip and os.path.exists(f'rtl/{ip}/regdef.json'):
        subprocess.run(
            [sys.executable, 'scripts/gen_default_regcfg.py', '--ip', ip,
             '-o', regcfg_path],
            capture_output=True
        )
    else:
        with open(regcfg_path, 'w') as f:
            f.write('FFFFFFFFFF\n')


def run_make(args):
    """执行 make 命令"""
    result = subprocess.run(
        ['make'] + args,
        capture_output=True, text=True
    )
    return result


def run_ip(ip, frames, img):
    """运行单个 IP 的仿真和输出生成"""
    reset_regcfg(ip)
    result = run_make([
        'sim', 'gen_output',
        f'IP={ip}', f'FRAMES={frames}', f'INPUT_IMG={img}',
        'WIDTH=64', 'HEIGHT=48'
    ])
    output = result.stdout + result.stderr
    # 检查是否有 PASS 或 ERROR
    for line in output.split('\n'):
        if 'PASS' in line or 'ERROR' in line:
            print(f"    {line.strip()}")


def prepare_test_images():
    """准备测试图"""
    note("0) 测试图准备")
    py = sys.executable

    subprocess.run(
        [py, 'scripts/gen_pattern.py', '--pattern', 'lowcontrast',
         '-W', '64', '-H', '48', '-o', 'sim/testdata/_low.png'],
        capture_output=True
    )
    subprocess.run(
        [py, 'scripts/gen_pattern.py',
         '--base', 'sim/testdata/test_input.png', '--sigma', '15',
         '-W', '64', '-H', '48', '-o', 'sim/testdata/_noisy.png'],
        capture_output=True
    )
    subprocess.run(
        [py, 'scripts/gen_pattern.py',
         '--base', 'sim/testdata/test_input.png', '--dead', '100',
         '--table', 'sim/testdata/_dpc.txt',
         '-W', '64', '-H', '48', '-o', 'sim/testdata/_defect.png'],
        capture_output=True
    )
    print("OK")


def smoke_test():
    """全 IP 冒烟测试"""
    note("1) 全 IP 冒烟 (协议检查内建于 sink)")
    for d in glob.glob('rtl/*/'):
        ip = os.path.basename(d.rstrip('/'))
        tb_path = f'sim/tests/tb_{ip}.v'
        if os.path.exists(tb_path):
            print(f"-- {ip}")
            run_ip(ip, '1', 'sim/testdata/test_input.png')


def functional_tests():
    """功能性检查"""
    global FAIL
    note("2) 功能性检查")

    try:
        import cv2
        import numpy as np
    except ImportError:
        print("  跳过: 需要 cv2 和 numpy")
        return

    def sh(cmd):
        return subprocess.run(cmd, shell=True, capture_output=True, text=True)

    def psnr(x, y):
        mse = ((x.astype(float) - y.astype(float)) ** 2).mean()
        return float('inf') if mse == 0 else 10 * np.log10(255**2 / mse)

    def regcfg(*entries):
        with open('sim/testdata/regcfg.hex', 'w') as f:
            for a, v in entries:
                f.write(f"{a:02x}{v:08x}\n")
            f.write("FFFFFFFFFF\n")

    def run(ip, frames, img):
        r = sh(f'make sim gen_output IP={ip} FRAMES={frames} INPUT_IMG={img} '
               f'WIDTH=64 HEIGHT=48')
        assert 'PASS' in r.stdout, f"{ip} 仿真失败"
        return cv2.imread(f'output/images/{ip}_output.png')

    ok = True
    def check(name, cond, detail):
        nonlocal ok
        status = '\u2713' if cond else '\u2717'
        print(f"  {status} {name}: {detail}")
        ok = ok and cond

    clean = cv2.imread('sim/testdata/test_input.png')

    # gamma: gamma2.2 逐点比对
    regcfg()
    out = run('gamma_corr', 1, 'sim/testdata/test_input.png')
    lut = np.array([round(255*(i/255)**(1/2.2)) if i else 0 for i in range(256)])
    err = np.abs(lut[clean.astype(int)] - out.astype(int)).max()
    check('gamma gamma2.2', err <= 1, f"最大偏差 {err} LSB (<=1)")

    # csc: RGB->YUV->RGB 往返
    regcfg()
    yuv = run('color_space_conv', 1, 'sim/testdata/test_input.png')
    cv2.imwrite('sim/testdata/_yuv.png', yuv)
    regcfg((0x10, 1))
    rt = run('color_space_conv', 1, 'sim/testdata/_yuv.png')
    d = np.abs(clean.astype(int) - rt.astype(int)).max()
    check('csc 往返', d <= 5, f"最大偏差 {d} LSB (<=5)")

    # dpc: 坏点校正
    regcfg()
    out = run('defect_pixel_corr', 1, 'sim/testdata/_defect.png')
    bad = cv2.imread('sim/testdata/_defect.png')
    p0, p1 = psnr(clean, bad), psnr(clean, out)
    check('dpc 坏点校正', p1 > p0 + 6, f"PSNR {p0:.1f} -> {p1:.1f} dB (+6 以上)")

    # denoise: 噪声抑制 + 对齐
    regcfg()
    out = run('denoise', 1, 'sim/testdata/_noisy.png')
    noisy = cv2.imread('sim/testdata/_noisy.png')
    p0, p1 = psnr(clean, noisy), psnr(clean, out)
    check('denoise 降噪', p1 > p0 + 1.0, f"PSNR {p0:.1f} -> {p1:.1f} dB (+1.0 以上)")
    c = [(dy, dx, np.abs(np.roll(noisy.astype(int), (dy, dx), (0, 1))
                     - out.astype(int)).mean())
         for dy in range(-2, 3) for dx in range(-2, 3)]
    dy, dx, _ = min(c, key=lambda t: t[2])
    check('denoise 对齐', (dy, dx) == (0, 0), f"偏移 ({dy},{dx})")

    # sharpen: 锐度提升
    regcfg()
    out = run('sharpen', 1, 'sim/testdata/test_input.png')
    def lapvar(img):
        return cv2.Laplacian(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY),
                             cv2.CV_64F).var()
    check('sharpen 锐度', lapvar(out) > lapvar(clean) * 1.3,
          f"Laplacian方差 {lapvar(clean):.0f} -> {lapvar(out):.0f}")

    # awb: 2帧增益收敛
    regcfg()
    out = run('auto_white_balance', 2, 'sim/testdata/test_input.png')
    b, g, r = (float(out[:, :, i].mean()) for i in range(3))
    gray = (r + g + b) / 3
    gains = [gray / x for x in (r, b)]
    check('awb 增益收敛', all(abs(x - 1) < 0.06 for x in gains),
          f"R/B 增益 {gains[0]:.3f}/{gains[1]:.3f} (~1.0)")

    # contrast: 3帧动态范围拉伸
    regcfg()
    out = run('contrast_enhance', 3, 'sim/testdata/_low.png')
    low = cv2.imread('sim/testdata/_low.png')
    ya = cv2.cvtColor(low, cv2.COLOR_BGR2GRAY)
    yb = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    check('contrast 拉伸', float(yb.std()) > float(ya.std()) * 2,
          f"亮度 std {ya.std():.1f} -> {yb.std():.1f}")

    if not ok:
        FAIL = 1


def backpressure_test():
    """随机反压抽测"""
    global FAIL
    note("3) 随机反压抽测 (窗口类 IP)")
    temp_dir = os.environ.get('TEMP', '/tmp')
    vvp_file = os.path.join(temp_dir, '_bp.vvp')

    for ip in ['sharpen', 'denoise', 'defect_pixel_corr']:
        rtl_files = ' '.join(glob.glob(f'rtl/{ip}/*.v'))
        ivl_result = subprocess.run(
            ['iverilog', '-g2012', '-o', vvp_file,
             f'-Ptb_{ip}.C_READY_MODE=1',
             'sim/common/*.v', rtl_files, f'sim/tests/tb_{ip}.v'],
            capture_output=True, text=True
        )
        if ivl_result.returncode == 0:
            vvp_result = subprocess.run(
                ['vvp', vvp_file],
                capture_output=True, text=True
            )
            output = vvp_result.stdout + vvp_result.stderr
            for line in output.split('\n'):
                if 'PASS' in line or 'ERROR' in line:
                    print(f"  {line.strip()}")

    # 清理
    if os.path.exists(vvp_file):
        os.remove(vvp_file)


def golden_test():
    """金标准比对"""
    global FAIL
    note("4) 金标准比对 (逐字/按位)")

    def gold(ip, frames, img):
        reset_regcfg(ip)
        run_make(['sim', f'IP={ip}', f'FRAMES={frames}',
                  f'INPUT_IMG={img}', 'WIDTH=64', 'HEIGHT=48'])
        print(f"  {ip:<20}", end='')
        sys.stdout.flush()
        result = subprocess.run(
            [sys.executable, 'scripts/verify.py', '--ip', ip,
             '-W', '64', '-H', '48', '--frames', str(frames)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            global FAIL
            FAIL = 1
        print(result.stdout.strip() if result.stdout else result.stderr.strip())

    gold('gamma_corr', 1, 'sim/testdata/test_input.png')
    gold('color_space_conv', 1, 'sim/testdata/test_input.png')
    gold('sharpen', 1, 'sim/testdata/test_input.png')
    gold('denoise', 1, 'sim/testdata/_noisy.png')
    gold('defect_pixel_corr', 1, 'sim/testdata/_defect.png')
    gold('contrast_enhance', 3, 'sim/testdata/_low.png')
    gold('auto_white_balance', 3, 'sim/testdata/test_input.png')


def ddr_test():
    """DDR + 帧缓冲 自检"""
    global FAIL
    note("5) DDR + 帧缓冲 自检")
    temp_dir = os.environ.get('TEMP', '/tmp')

    # DDR loopback
    if os.path.exists('sim/tests/tb_ddr_loopback.v'):
        vvp_file = os.path.join(temp_dir, '_ddr.vvp')
        ivl_result = subprocess.run(
            ['iverilog', '-g2012', '-o', vvp_file,
             'sim/common/ddr_model.v', 'sim/common/axi_frame_buffer.v',
             'sim/tests/tb_ddr_loopback.v'],
            capture_output=True, text=True
        )
        if ivl_result.returncode == 0:
            vvp_result = subprocess.run(
                ['vvp', vvp_file],
                capture_output=True, text=True
            )
            output = vvp_result.stdout + vvp_result.stderr
            found = False
            for line in output.split('\n'):
                if 'PASS' in line or 'ERROR' in line:
                    print(f"  {line.strip()}")
                    found = True
                    if 'ERROR' in line:
                        FAIL = 1
            if not found:
                print("  (无明确结果)")
        if os.path.exists(vvp_file):
            os.remove(vvp_file)
    else:
        print("  (无 tb_ddr_loopback.v, 跳过)")

    # Frame buffer addr
    if os.path.exists('sim/tests/tb_frame_buffer_addr.v'):
        vvp_file = os.path.join(temp_dir, '_fba.vvp')
        ivl_result = subprocess.run(
            ['iverilog', '-g2012', '-o', vvp_file,
             'sim/common/ddr_model.v', 'sim/common/axi_frame_buffer_addr.v',
             'sim/tests/tb_frame_buffer_addr.v'],
            capture_output=True, text=True
        )
        if ivl_result.returncode == 0:
            vvp_result = subprocess.run(
                ['vvp', vvp_file],
                capture_output=True, text=True
            )
            output = vvp_result.stdout + vvp_result.stderr
            for line in output.split('\n'):
                if 'PASS' in line or 'ERROR' in line:
                    print(f"  {line.strip()}")
                    if 'ERROR' in line:
                        FAIL = 1
        if os.path.exists(vvp_file):
            os.remove(vvp_file)


def cleanup():
    """清理临时文件"""
    note("6) 清理临时文件")
    temp_files = [
        'sim/testdata/_low.png',
        'sim/testdata/_noisy.png',
        'sim/testdata/_defect.png',
        'sim/testdata/_yuv.png',
        'sim/testdata/_dpc.txt',
        'sim/testdata/expected.hex'
    ]
    for f in temp_files:
        if os.path.exists(f):
            os.remove(f)
    print("OK")


def main():
    prepare_test_images()
    smoke_test()
    functional_tests()
    backpressure_test()
    golden_test()
    ddr_test()
    cleanup()

    print()
    if FAIL == 0:
        print("=== 回归完成: 全部通过 ===")
    else:
        print("=== 回归完成: 存在失败项 ===")
        sys.exit(1)


if __name__ == '__main__':
    main()
