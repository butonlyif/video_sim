# VIP Sim — Trae AI Coding Rules

本项目是围绕 awesom 视频处理 IP 的仿真验证平台，面向易灵思 TJ180 FPGA 开发板。

---

## 一、行为准则

**先想后写。不要假设。不要隐藏疑问。**

动手之前：明确你的假设、提出备选方案、指出更简单的路径。
写完代码：定义成功标准，用实际运行结果验证。

**简单优先。最少代码解决当前问题，不做假设性抽象。**

200 行能完成的别写 500 行。一个地方用一次的东西不单独抽函数。

**精准改动。只改需要改的地方，不美化周边代码。**

动已有代码时，不顺带改无关格式、注释、结构。风格不一致时跟随现有代码。

---

## 二、目录结构

```
video_sim/               ← 项目根
├── .trae/
│   └── rules/
│       └── project_rules.md   ← 本文件（AI 行为规则）
├── CLAUDE.md             ← AI 编码规范（通用）
├── docs/                 ← 项目文档
│   ├── DESIGN_SPEC.md    ← 系统设计规格
│   ├── EXTENSION_DESIGN.md ← 扩展设计文档
│   ├── USER_GUIDE.md     ← 用户使用说明书
│   └── dpc仿真超时问题修复建议.md
├── scripts/              ← 工具链（平台源码）
│   ├── gen_stimulus.py   ← 图像 → hex 激励
│   ├── gen_output.py     ← hex 结果 → 图像
│   ├── golden.py         ← 金标准模型（注册 MODELS + CONFIG）
│   ├── verify.py         ← 金标准比对
│   ├── analyze.py        ← 分析入口
│   ├── analyzers/        ← 5 个分析模块
│   │   ├── sharpness.py
│   │   ├── white_balance.py
│   │   ├── histogram.py
│   │   ├── psnr.py
│   │   └── gamma.py
│   ├── utils/
│   │   ├── console.py    ← 终端美化组件
│   │   └── pixel_format.py ← 像素格式打包/解包
│   └── gen_ip_spec.py    ← Spec 驱动代码生成器
├── rtl/                  ← IP RTL 源码（按 IP 名分子目录）
│   ├── passthrough/
│   ├── gamma_corr/
│   ├── dpc_3x3/
│   └── ...
├── sim/                  ← 仿真工作目录
│   ├── common/           ← AXI-Stream BFM
│   │   ├── axis_video_source.v
│   │   ├── axis_video_sink.v
│   │   └── reg_config.v
│   └── testdata/
│       ├── stimulus.hex
│       ├── result.hex
│       └── regcfg.hex
└── extension/            ← Trae/VS Code 扩展
    ├── extension.js      ← 扩展主逻辑（Webview 控制台）
    ├── package.json
    └── template/         ← 新建项目时释放的模板
```

---

## 三、IP 开发规范

### 3.1 RTL 目录结构（每个 IP 独立目录）

```
rtl/<ip_name>/
├── <ip_name>.v           ← 主模块（组合子模块）
├── <ip_name>_wrapper.v   ← AXI-Stream 端口包装（可选）
├── regdef.json           ← 寄存器描述（控制台表单来源）
├── golden.py             ← 金标准函数（可选，随 IP 附带）
└── ip.json               ← IP 清单（维度/分类/状态）
```

### 3.2 regdef.json 规范

```json
{
  "regs": [
    {
      "addr": "0x04",
      "name": "CTRL",
      "fields": [{ "name": "enable", "bits": [0, 0] }],
      "default": "0x00000001"
    },
    {
      "addr": "0x10",
      "name": "PARAM",
      "fields": [{ "name": "value", "bits": [7, 0] }],
      "default": "0x00000000"
    }
  ]
}
```

**default 值必须与 RTL 复位值严格一致**，否则 regcfg.hex 写进去后 IP 行为与仿真不符。

### 3.3 Testbench 骨架

每个 TB 必须包含：

1. **寄存器配置阶段**：`reg_config` BFM 逐个写寄存器并回读自检
2. **视频流阶段**：等待 `m_axis_tvalid && m_axis_tready` 后开始发像素
3. **结束条件**：`s_axis_tlast` 后再等 5 个时钟周期停止

```verilog
// 寄存器配置
reg_write(8'h04, 32'h00000001);   // enable
reg_write(8'h10, 32'h00000000);   // param

// 等待视频流开始（IP 配置完成后才会拉 valid）
wait(s_axis_tvalid && s_axis_tready);
$display("[%t] Video stream started", $time);
```

---

## 四、金标准维护规范

### 4.1 注册模型

在 `golden.py` 的 `MODELS` 字典中注册：

```python
MODELS = {
    'gamma_corr':    m_gamma,
    'dpc_3x3':       m_dpc,
    'awb_gamma_sharpen': m_chain,  # 级联模型
    # ...
}

CONFIG = {
    'gamma_corr':    {'frames': 1, 'tol': 0, 'frac': 0.0},
    'dpc_3x3':       {'frames': 1, 'tol': 0, 'frac': 0.0},
    # ...
}
```

### 4.2 逐位对照表（金标准与 RTL 一致性检查）

| IP | 输入位宽 | 定点规则 | 关键一致点 |
|---|---|---|---|
| `gamma_corr` | RGB888 | Q8.8 乘法，>>8 移位 | clamp [0,255] |
| `dpc_3x3` | RGB888 | 逐像素判断 | IMG_WIDTH/HEIGHT default=3840/2160 |
| `auto_white_balance` | RGB888 | R/G/B 各自累加，4帧滑动平均 | frac 参数覆盖首帧瞬态 |
| `sharpen` | RGB888 | 3x3 卷积，shift=8 | 边界像素直通 |

### 4.3 新增金标准步骤

1. 在 `golden.py` 末尾写 Python 函数（签名：`def m_xxx(fr, writes, fi, st)`）
2. 注册到 `MODELS['xxx'] = m_xxx`
3. 在 `CONFIG` 中设 `frames/tol/frac`
4. 运行 `make verify IP=xxx` 验证

### 4.4 级联模型注册

```python
def m_awb_gamma_sharpen(fr, writes, fi, st):
    r = m_awb(fr, writes, fi, st)
    r = m_gamma(r, writes, fi, st)
    return m_sharpen(r, writes, fi, st)

MODELS['awb_gamma_sharpen'] = m_awb_gamma_sharpen
CONFIG['awb_gamma_sharpen'] = {'frames': 3, 'tol': 0, 'frac': 0.02}
```

---

## 五、仿真控制台命令约定

扩展的 Webview 控制台命令与 `Makefile` 目标一一对应：

| Webview 按钮 | Makefile 目标 | 说明 |
|---|---|---|
| 运行仿真 | `make sim IP=<ip>` | 激励→iverilog→还原 |
| 生成激励 | `make stimulus IP=<ip>` | 仅生成 hex |
| 查看波形 | `make wave IP=<ip>` | 需 GTKWave |
| 图像分析 | `make analyze` | 全量分析 |
| 金标准比对 | `make verify IP=<ip>` | 逐像素比对 |
| 回归测试 | `make regression` | 全 IP 遍历 |

---

## 六、Spec 驱动开发规范

`.ip_spec.yaml` 生成 RTL + 金标准 + TB + regdef，同时生成天然一致。

**支持的内置算法类型**：

| type | 说明 |
|---|---|
| `passthrough` | 直通，bypass 寄存器控制 |
| `gain` | 增益乘法（定点 Q8.8） |
| `lut` | 查表变换（Gamma/亮度曲线） |
| `conv_1d` | 1D 卷积（锐化/降噪） |
| `csc` | 色彩空间转换（RGB↔YUV） |
| `sharpen` | 3x3 锐化卷积核 |
| `denoise` | 3x3 均值/中值滤波 |

**级联生成**：
```bash
python scripts/gen_ip_spec.py --chain awb,gamma,sharpen --register-chain awb_gamma_sharpen
```
自动生成 `rtl/awb_gamma_sharpen/` + 金标准链式函数。

---

## 七、已知平台限制与注意事项

1. **DDR 帧缓冲**：仅支持模拟（`ddr_model.v`），不支持真实 AXI 访问
2. **iverilog 限制**：`$readmemh` 只读 hex 文件，不支持二进制
3. **Windows 路径**：Python 脚本全用 `/` 分隔，已处理跨平台
4. **DPC IP**：regdef 中 IMG_WIDTH/HEIGHT default 必须是 3840/2160（与 RTL 复位值一致）
5. **regcfg.hex**：每次 `make sim` 前自动按 regdef.json 生成，**无需手动维护**

---

## 八、编码规范

- **Verilog**：时钟沿驱动，异步复位用 `negedge rst_n`，组合逻辑禁止 latching
- **Python**：PEP 8，工具链纯标准库（无外部依赖，除 opencv/numpy/pillow）
- **寄存器命名**：全大写，十六进制地址前缀 `0x`，位域用 `[hi:lo]` 格式
- **AXI-Stream**：视频格式固定 `{8'd0, R, G, B}`（32bit），tuser[0]=帧起始，tlast=行末
