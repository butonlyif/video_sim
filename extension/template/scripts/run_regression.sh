#!/bin/bash
# run_regression.sh — 项目内回归测试入口
# 用法: bash scripts/run_regression.sh   (在项目根目录执行)
# 对 rtl/ 下所有带 TB 的 IP 做冒烟测试; 对已知 IP 追加功能性检查。
set -u
cd "$(dirname "$0")/.."
PY=$(test -x .venv/bin/python && echo .venv/bin/python || echo python3)
FAIL=0

note() { echo; echo "=== $* ==="; }
reset_regcfg() { printf 'FFFFFFFFFF\n' > sim/testdata/regcfg.hex; }

run_ip() {  # run_ip <ip> <frames> <input>
    reset_regcfg
    make sim gen_output IP=$1 FRAMES=$2 INPUT_IMG=$3 WIDTH=64 HEIGHT=48 \
        2>&1 | grep -E "^PASS|^ERROR" | head -2
}

note "0) 测试图准备"
$PY scripts/gen_pattern.py --pattern lowcontrast -W 64 -H 48 \
    -o sim/testdata/_low.png > /dev/null
$PY scripts/gen_pattern.py --base sim/testdata/test_input.png --sigma 15 \
    -W 64 -H 48 -o sim/testdata/_noisy.png > /dev/null
$PY scripts/gen_pattern.py --base sim/testdata/test_input.png --dead 100 \
    --table sim/testdata/_dpc.txt -W 64 -H 48 \
    -o sim/testdata/_defect.png > /dev/null
echo "OK"

note "1) 全 IP 冒烟 (协议检查内建于 sink)"
for d in rtl/*/; do
    ip=$(basename "$d")
    [ -f "sim/tests/tb_$ip.v" ] || continue
    echo "-- $ip"
    run_ip "$ip" 1 sim/testdata/test_input.png
done

note "2) 功能性检查"
$PY - << 'EOF' || FAIL=1
import subprocess, sys
import cv2, numpy as np

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
    r = sh(f"make sim gen_output IP={ip} FRAMES={frames} INPUT_IMG={img} "
           f"WIDTH=64 HEIGHT=48")
    assert "PASS" in r.stdout, f"{ip} 仿真失败"
    return cv2.imread(f"output/images/{ip}_output.png")

ok = True
def check(name, cond, detail):
    global ok
    print(f"  {'✓' if cond else '✗'} {name}: {detail}")
    ok = ok and cond

clean = cv2.imread('sim/testdata/test_input.png')

# gamma: γ2.2 逐点比对
regcfg()
out = run('gamma_corr', 1, 'sim/testdata/test_input.png')
lut = np.array([round(255*(i/255)**(1/2.2)) if i else 0 for i in range(256)])
err = np.abs(lut[clean.astype(int)] - out.astype(int)).max()
check('gamma γ2.2', err <= 1, f"最大偏差 {err} LSB (≤1)")

# csc: RGB→YUV→RGB 往返
regcfg()
yuv = run('color_space_conv', 1, 'sim/testdata/test_input.png')
cv2.imwrite('sim/testdata/_yuv.png', yuv)
regcfg((0x10, 1))
rt = run('color_space_conv', 1, 'sim/testdata/_yuv.png')
# RGB→YUV→RGB 经两次 8bit 定点量化, ≤5 LSB 为定点往返固有误差
d = np.abs(clean.astype(int) - rt.astype(int)).max()
check('csc 往返', d <= 5, f"最大偏差 {d} LSB (≤5)")

# dpc: 坏点校正
regcfg()
out = run('defect_pixel_corr', 1, 'sim/testdata/_defect.png')
bad = cv2.imread('sim/testdata/_defect.png')
p0, p1 = psnr(clean, bad), psnr(clean, out)
check('dpc 坏点校正', p1 > p0 + 6, f"PSNR {p0:.1f} → {p1:.1f} dB (+6 以上)")

# denoise: 噪声抑制 + 对齐
regcfg()
out = run('denoise', 1, 'sim/testdata/_noisy.png')
noisy = cv2.imread('sim/testdata/_noisy.png')
# 5抽头十字核(中心权重0.5, 单行缓冲S近似N)为保边缘弱核, +1dB 即有效
p0, p1 = psnr(clean, noisy), psnr(clean, out)
check('denoise 降噪', p1 > p0 + 1.0, f"PSNR {p0:.1f} → {p1:.1f} dB (+1.0 以上)")
c = [(dy, dx, np.abs(np.roll(noisy.astype(int), (dy, dx), (0, 1))
                     - out.astype(int)).mean())
     for dy in range(-2, 3) for dx in range(-2, 3)]
dy, dx, _ = min(c, key=lambda t: t[2])
check('denoise 对齐', (dy, dx) == (0, 0), f"偏移 ({dy},{dx})")

# sharpen: 锐度提升 + 对齐
regcfg()
out = run('sharpen', 1, 'sim/testdata/test_input.png')
def lapvar(img):
    return cv2.Laplacian(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY),
                         cv2.CV_64F).var()
check('sharpen 锐度', lapvar(out) > lapvar(clean) * 1.3,
      f"Laplacian方差 {lapvar(clean):.0f} → {lapvar(out):.0f}")

# awb: 2帧增益收敛
regcfg()
out = run('auto_white_balance', 2, 'sim/testdata/test_input.png')
b, g, r = (float(out[:, :, i].mean()) for i in range(3))
gray = (r + g + b) / 3
gains = [gray / x for x in (r, b)]
check('awb 增益收敛', all(abs(x - 1) < 0.06 for x in gains),
      f"R/B 增益 {gains[0]:.3f}/{gains[1]:.3f} (≈1.0)")

# contrast: 3帧动态范围拉伸
regcfg()
out = run('contrast_enhance', 3, 'sim/testdata/_low.png')
low = cv2.imread('sim/testdata/_low.png')
ya = cv2.cvtColor(low, cv2.COLOR_BGR2GRAY)
yb = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
check('contrast 拉伸', float(yb.std()) > float(ya.std()) * 2,
      f"亮度 std {ya.std():.1f} → {yb.std():.1f}")

sys.exit(0 if ok else 1)
EOF

note "3) 随机反压抽测 (窗口类 IP)"
reset_regcfg
for ip in sharpen denoise defect_pixel_corr; do
    iverilog -g2012 -o /tmp/_bp.vvp -Ptb_$ip.C_READY_MODE=1 \
        sim/common/*.v rtl/$ip/*.v sim/tests/tb_$ip.v && \
    vvp /tmp/_bp.vvp | grep -E "^PASS|^ERROR" | head -1
done
rm -f /tmp/_bp.vvp

note "4) 金标准比对 (逐字/按位)"
gold() {  # gold <ip> <frames> <input>
    reset_regcfg
    make sim IP=$1 FRAMES=$2 INPUT_IMG=$3 WIDTH=64 HEIGHT=48 >/dev/null 2>&1
    printf '  %-20s ' "$1"
    $PY scripts/verify.py --ip $1 -W 64 -H 48 --frames $2 2>&1 || FAIL=1
}
gold gamma_corr        1 sim/testdata/test_input.png
gold color_space_conv  1 sim/testdata/test_input.png
gold sharpen           1 sim/testdata/test_input.png
gold denoise           1 sim/testdata/_noisy.png
gold defect_pixel_corr 1 sim/testdata/_defect.png
gold contrast_enhance  3 sim/testdata/_low.png
gold auto_white_balance 3 sim/testdata/test_input.png

note "5) DDR + 帧缓冲 自检"
if [ -f sim/tests/tb_ddr_loopback.v ]; then
    iverilog -g2012 -o /tmp/_ddr.vvp sim/common/ddr_model.v \
        sim/common/axi_frame_buffer.v sim/tests/tb_ddr_loopback.v 2>&1 | head -3
    vvp /tmp/_ddr.vvp 2>&1 | grep -E "^PASS|^ERROR" | head -1 || FAIL=1
    rm -f /tmp/_ddr.vvp
else
    echo "  (无 tb_ddr_loopback.v, 跳过)"
fi

note "6) 清理临时文件"
rm -f sim/testdata/_low.png sim/testdata/_noisy.png sim/testdata/_defect.png \
      sim/testdata/_yuv.png sim/testdata/_dpc.txt sim/testdata/expected.hex
echo "OK"

echo
if [ "$FAIL" -eq 0 ]; then echo "=== 回归完成: 全部通过 ==="
else echo "=== 回归完成: 存在失败项 ==="; exit 1; fi
