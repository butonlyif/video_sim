# VIP 仿真项目 — AI 代码生成规则

本项目是 awesom 视频处理 IP 的仿真验证环境。当用户要求生成/修改 IP 的 RTL 代码时，严格遵循以下规则，使生成的代码可以直接接入本项目的仿真环境。

---

## A. Spec 驱动开发流程（推荐）

**核心理念**：RTL 和金标准从同一份 `.ip_spec.yaml` 规格文件生成，天然逐位一致，无需人工对照。

```
你的 .ip_spec.yaml              gen_ip_spec.py
       │                                  │
       │                              ┌───┴───────────────────────┐
       │                              │ 自动生成 4 个文件：        │
       │                              │   RTL  ←────────────┐     │
       │                              │   TB   ←────────┐  │     │
       │                              │   regdef.json   │  │     │
       │                              │   golden.py ─────┼──┘     │
       │                              └───────────────────────────┘
       │                                      ↑
       └─────── docs/IP开发课题说明书.md（7 个课题已有规格）
       │
       └─────── AI 自然语言描述（全新 IP，如 "实现一个3x3锐化滤波器"）
```

### A.1 .ip_spec.yaml 完整格式

```yaml
# ── 1. 基本信息 ─────────────────────────────────────────────────────────────
name: my_filter           # IP 名称（英文、小写、下划线），用于文件/模块名
desc: 3-tap 锐化滤波器，系数 [1, -2, 1]，latency=1

# ── 2. 接口（固定，勿改）─────────────────────────────────────────────────────
interface:
  input_format: RGB888     # 目前只支持 RGB888
  output_format: RGB888

# ── 3. 算法规格 ─────────────────────────────────────────────────────────────
algorithm:
  type: conv_1d           # 内置类型（见下表）
  direction: horizontal
  kernel: [1, -2, 1]      # 整数系数，RTL 与 golden.py 必须完全一致
  fixed_point:
    shift: 3              # 算术右移位数（与 RTL 移位一致）
    clamp: [0, 255]       # 输出钳位

# ── 4. 寄存器（可选；无寄存器时省略整个 registers 块）─────────────────────────
registers:
  - addr: "0x04"
    name: CTRL
    access: RW
    default: "0x00000001"       # 必须与 RTL 复位值逐位一致
    desc: "bit0=enable(1开启) bit1=bypass(1旁路); 0x1=正常, 0x3=旁路"
  - addr: "0x10"
    name: COEF
    access: RW
    default: "0x00000004"
    desc: "锐化系数，Q3.0，范围 0~15，建议 4"

# ── 5. 流水线延迟（必须与 RTL 实际 latency 一致）───────────────────────────────
pipeline:
  latency: 1              # 1=无延迟；>1 时 RTL 自动插入 tuser/tlast 延迟寄存器
```

**内置 algorithm.type 及参数**：

| type | 说明 | 必需参数 |
|---|---|---|
| `passthrough` | 直通（无处理） | — |
| `gain` | 三通道统一增益 | `gain_bits`（默认 8） |
| `lut` | LUT 查表 | —（用户补充 lut 内容） |
| `conv_1d` | 1 维卷积 | `kernel: [k0, k1, k2]`、`shift` |
| `csc` | 色彩空间转换 | `coef: [9个数]`、`offset: [3个数]` |
| `sharpen` | 锐化 | `sharpen_factor`（默认 4） |
| `denoise` | 时域降噪 | `strength`（默认 4） |

### A.2 生成命令

```bash
# 方式 1：从 spec 文件生成
python scripts/gen_ip_spec.py --spec specs/my_filter.yaml

# 方式 2：从 AI 自然语言生成（Trae 扩展调用）
python scripts/gen_ip_spec.py --prompt "实现一个3x3锐化滤波器，系数[1,-2,1]，支持bypass"

# 生成后验证（金标准 + 仿真）
make verify IP=my_filter WIDTH=64 HEIGHT=48
```

**输出确认清单**：

```
✅ IP 'my_filter' 生成完成!
   文件:
     rtl/my_filter/my_filter.v      Verilog RTL（直接用，或在数据通路处修改）
     rtl/my_filter/regdef.json      寄存器描述（控制台表单数据源）
     sim/tests/tb_my_filter.v       Testbench 骨架（补充子模块例化，其余不改动）
     scripts/golden.py               金标准函数（自动追加到 MODELS/CONFIG）
```

### A.3 生成后如何修改

| 需要调整 | 操作位置 | 注意事项 |
|---|---|---|
| RTL 算法不正确 | `rtl/<ip>/<ip>.v` 数据通路部分 | 保留 AXI-Stream 端口和总线逻辑不变 |
| 金标准不匹配 | `scripts/golden.py` 的 `m_<ip>` 函数 | 见 §D 金标准维护 |
| 寄存器不对 | `rtl/<ip>/regdef.json` | `default` 必须与 RTL `initial/reset` 值一致 |

---

## B. 文档参照开发流程（7 个已有课题）

对于 `docs/IP开发课题说明书.md` 中已有的 7 个课题（色彩空间转换、Gamma校正、自动白平衡、坏点校正、降噪、锐化、对比度增强），直接参照文档生成代码。

**同样推荐用 A 节的 `.ip_spec.yaml`**（将文档中的算法描述转为 YAML），这样金标准也会自动生成。

---

## C. 文件放置规则（必须遵守）

| 文件             | 路径                          | 说明                       |
| -------------- | --------------------------- | ------------------------ |
| IP 顶层模块        | `rtl/<ip_name>/<ip_name>.v` | 模块名与文件名一致，小写下划线           |
| IP 子模块         | `rtl/<ip_name>/*.v`         | 同目录                      |
| 寄存器描述          | `rtl/<ip_name>/regdef.json` | 仿真控制台据此渲染寄存器编辑界面，**必须提供** |
| Testbench      | `sim/tests/tb_<ip_name>.v`  | 顶层模块名 `tb_<ip_name>`     |
| IP 清单（可选）     | `rtl/<ip_name>/ip.json`     | 维度变换 + 分类元数据，见下文；缺省=逐点恒等 |
| 金标准（可选）       | `rtl/<ip_name>/golden.py`   | 随 IP 走的金标准，见 §D.0；缺省回退内置 |

**regdef.json 格式**（addr/default 为 0x 前缀十六进制字符串，access 为 RO/RW）：

```json
{
  "registers": [
    {"addr": "0x04", "name": "CTRL", "access": "RW",
     "default": "0x00000001",
     "desc": "bit0=enable(1开启) bit1=bypass(1旁路); 0x1=正常, 0x3=旁路"}
  ]
}
```

缺省值必须与 RTL 复位值逐位一致。**desc 必须写成位字段格式**
（`bitN=名称(取值含义)`），不得写 `[0]enable [1]bypass` 这种易被误读为
"值0=enable、值1=bypass"的简写；位掩码型寄存器建议在 desc 末尾给常用
组合值示例（如 `0x1=正常, 0x3=旁路`）。

**多 IP 组合设计的统一寄存器表**：由多个子 IP 级联组成的设计
（如 AWB→锐化 流水线），必须把各子 IP 的寄存器统一编入一个地址空间：

1. RTL 顶层按基址分段译码 `cfg_addr`，每个子 IP 占一段（建议 0x40 间隔）；
   子 IP 实例的 `cfg_addr` 接 `cfg_addr - 基址`，`cfg_rdata` 按段选择回读
2. 组合设计的 `regdef.json` 用 `includes` 引用子 IP 并声明基址，
   仿真控制台会自动平移地址、加前缀，合并成统一寄存器表展示：

```json
{
  "includes": [
    { "ip": "auto_white_balance", "base": "0x00", "prefix": "AWB_" },
    { "ip": "sharpen", "base": "0x40", "prefix": "SHARP_" }
  ],
  "registers": []
}
```

3. 子 IP 自身的 regdef.json 保持独立（单测时仍可用），组合层不复制内容

**ip.json 清单（可选，几何/帧间类 IP 用）**：声明输出维度变换与 IP 分类，
缺省（无此文件）= 逐点恒等，现有 IP 不受影响。

```json
{
  "category": "geometric",                       // pointwise | geometric | interframe
  "dims": { "out_w": "in_h", "out_h": "in_w" }   // 表达式, 变量 in_w/in_h; 缺省恒等
}
```

平台据此：
- `verify` 按输入维度建模、按输出维度比对（转置/缩放等维度变换 IP 的正确入口）；
- `make sim` 给 sink 注入 `C_OUT_WIDTH/C_OUT_HEIGHT`（仅 OUT≠IN 时，故其 tb 须声明这两个参数）；
- `make analyze` 按分类切换：`geometric/interframe` 跳过 PSNR/差异图等逐像素对齐指标
  （会误导），改以 `verify` 金标准为准；`pointwise` 全开。

放置正确后，仿真控制台和 `make all IP=<ip_name>` 会自动发现该 IP。

---

## D. 金标准维护

金标准有两种维护方式，**新 IP 推荐随 IP 走（D.0）**，内置集中式（D.1）作为迁移期回退。

### D.0 随 IP 自动发现（推荐）

把金标准放到 `rtl/<ip>/golden.py`，平台启动时由 `scripts/golden.py` 自动扫描并导入，
覆盖内置 `MODELS/CONFIG`——无需改动公共文件，新 IP 自包含、不引发合并冲突。

```python
# rtl/my_filter/golden.py
import golden                              # 复用 clamp8 / neighbors / final_regs 等辅助

CONFIG = {'frames': 1, 'tol': 0, 'frac': 0.0}

def model(frame, writes, frame_idx, state):
    ...
    return out_frame                       # 函数名固定为 model；导出 CONFIG 可选
```

找不到 `rtl/<ip>/golden.py` 时回退到 `scripts/golden.py` 内置模型（见 D.1）。

### D.1 手动修改/添加金标准（内置/回退）

```python
# scripts/golden.py

# 1. 在 MODELS 注册
MODELS = {
    'passthrough': m_passthrough, 'gamma_corr': m_gamma,
    ...
    'my_filter': m_my_filter,       # ← 新增
}

# 2. 在 CONFIG 配置
CONFIG = {
    'passthrough': {'frames': 1, 'tol': 0, 'frac': 0.0},
    ...
    'my_filter': {'frames': 1, 'tol': 0, 'frac': 0.0},  # ← 新增
}
```

### D.2 金标准函数编写规范

```python
def m_my_filter(fr, writes, fi, st):
    # 1. 读寄存器（from regcfg.hex 的 last-write-wins）
    regs = final_regs(writes, {"0x04": "0x00000001"})
    enable = regs.get(0x04, 0x1) & 1
    bypass = (regs.get(0x04, 0x1) >> 1) & 1
    if not enable or bypass:
        return fr.copy()

    # 2. 复现 RTL 的整数/定点运算
    #    - 算术右移用 np.right_shift（对负数向下取整，等价 Verilog >>>）
    #    - clamp 用 clamp8() = np.clip(..., 0, 255)
    #    - 窗口类用 neighbors()（边界复制，与 RTL 对齐）

    return clamp8(result)
```

**CONFIG 参数含义**：

| 参数 | 含义 | 设置建议 |
|---|---|---|
| `frames` | 比对帧数 | 无状态 IP=1；含帧内瞬态=2；含帧间延迟=3 |
| `tol` | 像素容差（绝对值） | 定点截断误差可设 1~2；精确算法设 0 |
| `frac` | 容许失配像素比例 | 瞬态像素（如 AWB 首帧）可设 0.02；精确算法设 0.0 |

**逐位精确保证**：

```
Verilog                         Python (golden.py)
───────────────────────────────────────────────────────────────
reg signed [17:0] acc;         np.int64
acc >>> 3  (算术右移)           np.right_shift(acc, 3)
(clamp 0~255)                  clamp8(acc)
边界镜像填充                   np.pad(..., mode='edge')
reg [7:0] r = tdata[23:16];   r = (px >> 16) & 0xFF
```

### D.3 级联 IP 的金标准

使用 `gen_ip_spec.py` 生成级联组合的金标准（自动对接）：

```bash
# 生成级联组合：rtl/awb_gamma_sharpen/awb_gamma_sharpen.v
python scripts/gen_ip_spec.py \
    --chain awb,gamma,sharpen \
    --register-chain awb_gamma_sharpen

# 自动注册到 golden.py（追加 m_awb_gamma_sharpen）
# 金标准 = m_awb ∘ m_gamma ∘ m_sharpen（函数组合）
```

**手动注册级联模型**（若 golden.py 中尚无）：

```python
def m_awb_gamma_sharpen(fr, writes, fi, st):
    r = fr
    r = m_awb(r, writes, fi, st)
    r = m_gamma(r, writes, fi, st)
    r = m_sharpen(r, writes, fi, st)
    return r

MODELS['awb_gamma_sharpen'] = m_awb_gamma_sharpen
CONFIG['awb_gamma_sharpen'] = {'frames': 3, 'tol': 0, 'frac': 0.0}
```

---

## E. 接口约定（与仿真 BFM 对接）

- 数据接口：AXI-Stream，**单像素 32bit tdata**，RGB888 排列 `{8'd0, R[7:0], G[7:0], B[7:0]}`
- 信号：`aclk` / `aresetn`(低有效) / `s_axis_*`(tvalid,tready,tdata,tuser,tlast) / `m_axis_*` 同构
- `tuser` = 帧首像素(SOF)，`tlast` = 行尾像素(EOL)，必须随数据同步透传或正确再生
- **必须正确处理 `tready` 反压**（sink 可能随机反压），不允许丢失或重复像素
- 接口模板参考 `rtl/passthrough/passthrough.v`
- 可配置参数的 IP 增加寄存器接口 `cfg_addr/cfg_wdata/cfg_wen/cfg_ren/cfg_rdata`

---

## F. Testbench 规则

以 `sim/tests/tb_passthrough.v` 为模板复制修改：

1. 必须保留参数 `C_WIDTH / C_HEIGHT / C_FRAMES`（Makefile 通过 `-P` 注入）
2. 必须例化 `axis_video_source`（读 `sim/testdata/stimulus.hex`）和 `axis_video_sink`（写 `sim/testdata/result.hex`），二者位于 `sim/common/`，**不得修改 BFM 源码**
3. 保留 `+WAVE` 波形开关、sink_done 后 `$finish`、超时保护
4. **寄存器配置必须用 `reg_config` BFM**（`sim/common/reg_config.v`，读
   `sim/testdata/regcfg.hex`），cfg_* 信号声明为 wire 接到 BFM；**`cfg_rdata`
   必须从 DUT 接回 BFM**（`.cfg_rdata(cfg_rdata)`），BFM 据此做寄存器读写自检：
   写完后逐个回读比对，打印 `REGCHK PASS/FAIL`，再放行视频流。仿真控制台运行时
   按界面寄存器值生成 regcfg.hex。**迁移**：旧 TB 若未接 `cfg_rdata`，回读得到 x/z
   会报 `REGCHK FAIL`，补上该连接即可（视频流不受影响，`done` 仍会拉高）。
5. `axis_video_source` 的 `enable` 端口必须接 `reg_config` 的 `done`
   （保证寄存器"配置+自检"完成后视频流才启动）；无寄存器的 IP 接 `1'b1`

**标准 TB 骨架**（生成新 TB 时以此为准, 仅替换 <ip_name> 与 DUT 例化）：

```verilog
`timescale 1ns / 1ps
module tb_<ip_name>;

parameter C_WIDTH  = 64;
parameter C_HEIGHT = 48;
parameter C_FRAMES = 1;
parameter C_STREAM = 0;   // 0=单帧replay; 1=视频流式读多帧 (Makefile VIDEO=1 注入)
parameter C_STIMULUS_FILE = "sim/testdata/stimulus.hex";
parameter C_RESULT_FILE   = "sim/testdata/result.hex";
parameter C_READY_MODE    = 0;
localparam C_DATA_WIDTH = 32;

reg aclk = 1'b0;  always #4 aclk = ~aclk;   // 125 MHz
reg aresetn = 1'b0;

wire        src_tvalid, src_tready, src_tuser, src_tlast;
wire [31:0] src_tdata;
wire        dut_tvalid, dut_tready, dut_tuser, dut_tlast;
wire [31:0] dut_tdata;
wire        src_done, sink_done;
wire [31:0] src_cnt, sink_cnt;

wire [7:0]  cfg_addr;   wire [31:0] cfg_wdata;
wire        cfg_wen, cfg_ren, cfg_done;
wire [31:0] cfg_rdata;

reg_config u_regcfg (
    .aclk(aclk), .aresetn(aresetn),
    .cfg_addr(cfg_addr), .cfg_wdata(cfg_wdata),
    .cfg_wen(cfg_wen), .cfg_ren(cfg_ren),
    .cfg_rdata(cfg_rdata),                 // 回读: 寄存器读写自检需要
    .done(cfg_done));

axis_video_source #(
    .C_DATA_WIDTH(C_DATA_WIDTH), .C_WIDTH(C_WIDTH), .C_HEIGHT(C_HEIGHT),
    .C_FRAMES(C_FRAMES), .C_STREAM(C_STREAM), .C_STIMULUS_FILE(C_STIMULUS_FILE)
) u_source (
    .aclk(aclk), .aresetn(aresetn), .enable(cfg_done),
    .m_axis_tvalid(src_tvalid), .m_axis_tready(src_tready),
    .m_axis_tdata(src_tdata), .m_axis_tuser(src_tuser),
    .m_axis_tlast(src_tlast), .frame_done(src_done), .pixel_cnt(src_cnt));

<ip_name> u_dut (
    .aclk(aclk), .aresetn(aresetn),
    .cfg_addr(cfg_addr), .cfg_wdata(cfg_wdata), .cfg_wen(cfg_wen),
    .cfg_ren(cfg_ren), .cfg_rdata(cfg_rdata),
    .s_axis_tvalid(src_tvalid), .s_axis_tready(src_tready),
    .s_axis_tdata(src_tdata), .s_axis_tuser(src_tuser), .s_axis_tlast(src_tlast),
    .m_axis_tvalid(dut_tvalid), .m_axis_tready(dut_tready),
    .m_axis_tdata(dut_tdata), .m_axis_tuser(dut_tuser), .m_axis_tlast(dut_tlast));

axis_video_sink #(
    .C_DATA_WIDTH(C_DATA_WIDTH), .C_WIDTH(C_WIDTH), .C_HEIGHT(C_HEIGHT),
    .C_FRAMES(C_FRAMES), .C_READY_MODE(C_READY_MODE),
    .C_RESULT_FILE(C_RESULT_FILE)
) u_sink (
    .aclk(aclk), .aresetn(aresetn),
    .s_axis_tvalid(dut_tvalid), .s_axis_tready(dut_tready),
    .s_axis_tdata(dut_tdata), .s_axis_tuser(dut_tuser),
    .s_axis_tlast(dut_tlast), .frame_done(sink_done), .pixel_cnt(sink_cnt));

initial if ($test$plusargs("WAVE")) begin
    $dumpfile("output/waves/<ip_name>.vcd");
    $dumpvars(0, tb_<ip_name>);
end

initial begin
    repeat (10) @(posedge aclk);
    aresetn = 1'b1;
    wait (sink_done);
    repeat (10) @(posedge aclk);
    $display("PASS: 仿真完成, 共接收 %0d 像素 (%0dx%0d x %0d帧)",
             sink_cnt, C_WIDTH, C_HEIGHT, C_FRAMES);
    $finish;
end

initial begin
    #(C_WIDTH * C_HEIGHT * C_FRAMES * 8 * 100 + 500_000);
    $display("ERROR: 仿真超时");
    $finish;
end

endmodule
```

---

## G. 编码规范

- 纯 Verilog-2001（iverilog -g2012 可编译），不用 SystemVerilog 类/接口
- 时序逻辑统一 `always @(posedge aclk)`，复位用同步判断 `if (!aresetn)`
- 命名：模块/信号小写下划线，参数 `C_` 前缀大写
- 流水线设计目标 125MHz，1 像素/时钟吞吐

---

## H. 验证闭环

```bash
# spec 驱动生成的 IP
python scripts/gen_ip_spec.py --spec specs/my_filter.yaml
make all IP=my_filter WIDTH=64 HEIGHT=48   # 激励→仿真→还原→分析

# 文档参照生成的 IP
make all IP=gamma_corr WIDTH=64 HEIGHT=48
```

**统计类 IP 必须用多帧验证**：自动白平衡、自动对比度等依赖帧统计的 IP，
增益/参数在第 N 帧统计、第 N+1 帧才生效，单帧仿真输出必然等于输入。
此类 IP 验证时必须 `FRAMES=2`（或更多）：

```bash
make all IP=auto_white_balance WIDTH=64 HEIGHT=48 FRAMES=2
```

### 需要"上一帧全部像素"的 IP 用 DDR 帧缓冲

区分两类帧间需求：
- **只需统计量**（AWB 的累加和、对比度的直方图）→ 片上寄存器，不用 DDR
- **需上一帧全部像素**（时域降噪、帧平均、运动检测、帧率转换）→ 用片外 DDR 帧缓冲

后者例化 `sim/common/axi_frame_buffer.v` + `sim/common/ddr_model.v`（标准 AXI4，
**勿改这两个公共模块**）。帧缓冲对外是简单的"写帧流 wr_*/读上一帧流 rd_*"，
IP 把当前帧写入、同时消费 rd 端的上一帧像素做处理（读写 1:1 配速）。
`prev_valid` 首帧为 0（无上一帧时直通）。详见 `docs/IP_SPEC_ddr_frame_buffer.md`。
DDR 规格（位宽/容量/延迟）可按 IP 需求调参。

**几何变换类 IP（转置/缩放/旋转）需自定义读地址**：`axi_frame_buffer.v` 只做线性
ping-pong（`rptr++`），无法表达列优先/步进/仿射读序。改用 `sim/common/axi_frame_buffer_addr.v`：
写帧流不变，读侧改为 IP 提供 `rd_addr + rd_req`、封装回 `rd_data + rd_valid`，
AXI 时序与双槽 ping-pong 仍由封装处理。容量按 **2 槽自适配**——例化 `ddr_model` 时用
`localparam DDR_WORDS = 2 * C_WIDTH * C_HEIGHT;`，不要按帧大小手算写死（真实踩坑点：
写死容量换大分辨率即越界失配）。自检参考 `sim/tests/tb_frame_buffer_addr.v`。

---

## I. 自定义图像/视频预处理（用户用自然语言驱动）

用户可能让你填写 `scripts/preprocess_custom.py` 的 `process(frame, idx, rng)` 函数，
对输入图像/视频做自定义预处理（在仿真之前施加）。约定：

- `frame`：H×W×3 的 **BGR uint8** numpy 数组（OpenCV 格式）
- `idx`：帧序号（0 起；图像恒为 0；视频可用它做随时间变化的效果）
- `rng`：`np.random.Generator`，所有随机性用它以保证可复现
- 返回：同形状 **uint8** 数组（务必 `np.clip(x,0,255).astype(np.uint8)`）
- 只改函数体，保持签名不变；可用 cv2/numpy
- 用户在控制台"预处理...→自定义算子"运行，或 `python scripts/preprocess.py
  -i in.mp4 -o out.mp4 --custom scripts/preprocess_custom.py`

按用户的自然语言需求（如"模拟低光照""加运动模糊""暗角扫过"）实现 process()。

---

## J. 实战经验教训（来自真实 IP 调试，生成代码时必须遵守）

以下问题在本环境中实际发生过，每条都导致过仿真失败或图像损坏：

### J.1 窗口类 IP（3×3 卷积/锐化/降噪）的对齐规则

- **tuser/tlast 必须跟随中心像素走流水线**，不得直接透传输入的标记
  （否则输出内容与坐标错开，整图错位，且每帧末行丢失）
- **列计数器必须每行清零**（SOF *和* 行尾后都要清零），列号才是行缓冲的
  正确地址；只在 SOF 清零会变成"全帧像素序号"，窗口数据全错
- 行尾/帧尾必须冲刷：用边界镜像补缺失的邻居，保证**每帧输出像素数
  严格等于输入**（否则 sink 等不齐数据，仿真挂死）
- 边界（首行/首列/末列）用镜像/复制，不得读行缓冲中的跨帧残留数据

### J.2 统计类 IP（AWB/直方图均衡）的乒乓缓冲模式

- 帧与帧之间**没有空闲周期**（视频流背靠背），任何"帧间计算"都必须
  后台进行：统计数组、结果 LUT 都要**双缓冲乒乓**
  （帧 N 统计 → 帧 N+1 后台构建+清零旧统计 → 帧 N+2 切换生效）
- 归一化除法不得按分辨率硬编码系数（如 `×85>>10` 只对 64×48 成立），
  用 30~40 拍的串行移位减法除法器现算倒数
- SOF 拍翻转的状态（lut_valid/lut_sel 等）：SOF 像素本身读到的还是
  旧值（非阻塞赋值），需组合前馈让首像素用切换后的新值

### J.3 仿真数组初始化

- 所有 reg 数组（直方图、行缓冲、LUT、系数表）必须加 `initial` 块初始化，
  否则 X 态会传染（`X+1=X`），整帧输出变成 `00xxxxxx`
- 算法上能用边界镜像替代"读未写过的存储"时优先用镜像
- **不要用 `assign` 连续赋值去读 reg 数组**（如 `assign y = f(coef[i])`，
  f 内部读模块级 memory）：iverilog 对"函数/连续赋值读 memory 数组"不建立
  敏感性，时刻 0 读到 X 后永不重算、X 卡死；且运行时改数组值不会重新求值。
  正确做法：把读数组的运算放进 `always @(posedge aclk)` 时钟块内调用（每拍
  重算，读当前值）。色彩空间转换的矩阵系数表踩过此坑。

### J.4 AXI-Stream 握手细则

- `m_axis_tvalid` 一旦拉高，必须保持到 `m_axis_tready` 接受后才允许
  变化；输出寄存器只在 `!m_axis_tvalid || m_axis_tready` 时更新
- 简单 1 进 1 出 IP 的标准写法：`assign s_axis_tready = !m_axis_tvalid || m_axis_tready`
- 生成后必须用随机反压复测：
  `iverilog -g2012 -Ptb_<ip>.C_READY_MODE=1 ...`，像素不得丢失或重复

- 仿真日志出现 `PASS: 仿真完成` 且无 `ERROR:` 才算通过
- 算法效果通过仿真控制台的分析面板验证（锐度/白平衡/直方图/PSNR）
- 修改代码后重新运行上述命令直到通过
