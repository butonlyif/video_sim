# DPC 仿真超时问题分析及平台修复建议

## 问题现象

运行 `python scripts/sim.py sim IP=dpc_3x3` 时，仿真超时退出：

```
REGCHK PASS: 寄存器读写自检通过 (6/6 读回一致)
ERROR: 仿真超时
```

## 根因定位

**结论：DPC IP 的 RTL 功能正常，超时由仿真平台的 regcfg.hex 配置缺失导致。**

### 因果链

1. `sim.py` 的 `t_sim()` 在仿真前**未生成 `regcfg.hex`**，仅生成了 `stimulus.hex`。
2. `regdef.json` 中 `IMG_WIDTH` / `IMG_HEIGHT` 的 default 声明为 `0x00000000`（与 RTL 复位值 `C_MAX_WIDTH=3840` / `C_MAX_HEIGHT=2160` 不一致）。
3. 若存在残留的 `regcfg.hex`（被 `gen_default_regcfg.py` 以 default 值生成且未传入 `-W/-H`），`reg_config` BFM 会将 width/height 覆写为 0。
4. RTL 中输出有效条件为 `out_valid_reg <= (pixel_count > img_width + 12'd2) && (out_y < img_height)`，当 `img_height=0` 时 `out_y < 0` 对无符号数恒为 false，**永远不产生输出**。
5. `axis_video_sink` 等不到 `sink_done`，testbench 超时 watchdog 触发 `$finish`。

### 验证证据

| 场景 | regcfg WIDTH/HEIGHT | 仿真结果 |
|------|---------------------|----------|
| 残留 regcfg（WIDTH=0, HEIGHT=0） | `1000000000` / `1400000000` | 超时 |
| 正确生成 regcfg（WIDTH=64, HEIGHT=48） | `1000000040` / `1400000030` | PASS，接收 3072 像素 |

---

## 修复建议（针对 VIP Sim 平台）

以下问题应在 VIP Sim 平台代码中统一修复，而非在各 IP 项目内打补丁。

### 修复 1：`sim.py` 在仿真前自动生成 regcfg.hex

**文件**：平台 `scripts/sim.py`

**问题**：`t_sim()` 缺少 regcfg 生成步骤，而 `run_regression.py` 的 `reset_regcfg()` 有此步骤。两者不一致。

**修复**：在 `t_sim()` 中增加 regcfg 生成，与 `run_regression.py` 对齐：

```python
def t_sim():
    t_gen_stimulus()
    _gen_regcfg()   # 新增
    _compile_and_run(stream=(V['VIDEO'] == '1'))

def _gen_regcfg():
    """按当前 IP 的 regdef.json 生成 regcfg.hex，WIDTH/HEIGHT 用仿真分辨率覆盖。"""
    ip = V['IP']
    regdef = os.path.join('rtl', ip, 'regdef.json')
    if os.path.exists(regdef):
        must(sh([PY, 'scripts/gen_default_regcfg.py', '--ip', ip,
                 '-o', 'sim/testdata/regcfg.hex',
                 '-W', V['WIDTH'], '-H', V['HEIGHT']]))
    else:
        # 无 regdef 的 IP（如 passthrough）：写空配置（仅哨兵行）
        with open('sim/testdata/regcfg.hex', 'w') as f:
            f.write('FFFFFFFFFF\n')
```

同样需要对 `t_video_sim()` 做相同处理。

### 修复 2：`regdef.json` 的 default 值应与 RTL 复位值一致

**文件**：各 IP 的 `rtl/<ip>/regdef.json`

**问题**：`dpc_3x3` 的 regdef.json 中 `IMG_WIDTH` default 为 `0x00000000`，但 RTL 复位值为 `C_MAX_WIDTH[15:0]`（即 3840）。平台文档已要求二者逐位一致（见 `gen_default_regcfg.py` 注释），但实际未遵守。

**修复**：更新 `rtl/dpc_3x3/regdef.json`：

```json
{
  "addr": "0x10",
  "name": "IMG_WIDTH",
  "access": "RW",
  "default": "0x00000F00",   ← 3840
  "desc": ""
},
{
  "addr": "0x14",
  "name": "IMG_HEIGHT",
  "access": "RW",
  "default": "0x00000870",   ← 2160
  "desc": ""
}
```

> 注意：即便 regdef default 不修正，修复 1 也能保证仿真时传入正确的分辨率。但保持 default 一致可避免其他依赖 regdef 的工具链出错。

### 修复 3：`run_regression.py` 中 DPC 的 IP 名称不匹配

**文件**：平台 `scripts/run_regression.py`

**问题**：功能性检查和金标准比对使用 `defect_pixel_corr` 作为 IP 名，但实际目录和 testbench 名为 `dpc_3x3`。会导致 `iverilog` 找不到 `tb_defect_pixel_corr.v` 而编译失败。

**修复**：将 `run_regression.py` 中所有 `defect_pixel_corr` 替换为 `dpc_3x3`：

- 第 156 行：`out = run('defect_pixel_corr', ...)` → `run('dpc_3x3', ...)`
- 第 211 行：`for ip in [..., 'defect_pixel_corr']` → `'dpc_3x3'`
- 第 259 行：`gold('defect_pixel_corr', ...)` → `gold('dpc_3x3', ...)`

同样问题存在于 `scripts/run_regression.sh`（第 98、148、166 行）。

### 修复 4：`run_regression.py` 功能性检查中 DPC 的 regcfg 为空

**文件**：平台 `scripts/run_regression.py`

**问题**：`functional_tests()` 中 DPC 测试调用 `regcfg()` 无参数（第 155 行），写入空配置（仅哨兵行）。此时 RTL 使用复位默认值 3840×2160，对 64×48 输入永远不产出有效输出。

**修复**：将 `regcfg()` 替换为 `reset_regcfg('dpc_3x3', 64, 48)`：

```python
# dpc: 坏点校正
reset_regcfg('dpc_3x3', 64, 48)   # 替换原来的 regcfg()
out = run('dpc_3x3', 1, 'sim/testdata/_defect.png')
```

---

## 修复优先级

| 优先级 | 修复项 | 影响范围 |
|--------|--------|----------|
| P0（必须） | 修复 1：`sim.py` 自动生成 regcfg | 所有带 regdef 的 IP 单独仿真 |
| P1（重要） | 修复 3：IP 名称 `defect_pixel_corr` → `dpc_3x3` | 回归测试 DPC 项完全跑不通 |
| P1（重要） | 修复 4：功能性检查 DPC 的 regcfg 为空 | 回归测试 DPC 功能检查超时 |
| P2（建议） | 修复 2：regdef default 与 RTL 一致 | 工具链一致性，防御性修复 |

---

## 临时绕过方法（当前项目内）

在平台修复落地前，手动生成正确的 regcfg 即可绕过：

```bash
python3 scripts/gen_default_regcfg.py --ip dpc_3x3 -W 64 -H 48
python3 scripts/sim.py sim IP=dpc_3x3
```
