# VIP 仿真项目 — AI 代码生成规则

本项目是 awesom 视频处理 IP 的仿真验证环境。当用户要求生成/修改 IP 的 RTL 代码时，严格遵循以下规则，使生成的代码可以直接接入本项目的仿真环境。

## IP 规格依据

IP 的功能需求、接口标准、算法说明见 `docs/IP开发课题说明书.md`（7 个课题：色彩空间转换、Gamma校正、自动白平衡、坏点校正、降噪、锐化、对比度增强）。生成任何 IP 代码前先阅读该文档中对应课题的章节。

## 文件放置规则（必须遵守）

| 文件             | 路径                          | 说明                       |
| -------------- | --------------------------- | ------------------------ |
| IP 顶层模块        | `rtl/<ip_name>/<ip_name>.v` | 模块名与文件名一致，小写下划线           |
| IP 子模块         | `rtl/<ip_name>/*.v`         | 同目录                      |
| 寄存器描述          | `rtl/<ip_name>/regdef.json` | 仿真控制台据此渲染寄存器编辑界面，**必须提供** |
| Testbench      | `sim/tests/tb_<ip_name>.v`  | 顶层模块名 `tb_<ip_name>`     |

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

放置正确后，仿真控制台和 `make all IP=<ip_name>` 会自动发现该 IP。

## 接口约定（与仿真 BFM 对接）

- 数据接口：AXI-Stream，**单像素 32bit tdata**，RGB888 排列 `{8'd0, R[7:0], G[7:0], B[7:0]}`
- 信号：`aclk` / `aresetn`(低有效) / `s_axis_*`(tvalid,tready,tdata,tuser,tlast) / `m_axis_*` 同构
- `tuser` = 帧首像素(SOF)，`tlast` = 行尾像素(EOL)，必须随数据同步透传或正确再生
- **必须正确处理 `tready` 反压**（sink 可能随机反压），不允许丢失或重复像素
- 接口模板参考 `rtl/passthrough/passthrough.v`
- 可配置参数的 IP 增加寄存器接口 `cfg_addr/cfg_wdata/cfg_wen/cfg_ren/cfg_rdata`，地址映射遵循课题说明书 2.4 节

## Testbench 规则

以 `sim/tests/tb_passthrough.v` 为模板复制修改：

1. 必须保留参数 `C_WIDTH / C_HEIGHT / C_FRAMES`（Makefile 通过 `-P` 注入）
2. 必须例化 `axis_video_source`（读 `sim/testdata/stimulus.hex`）和 `axis_video_sink`（写 `sim/testdata/result.hex`），二者位于 `sim/common/`，**不得修改 BFM 源码**
3. 保留 `+WAVE` 波形开关、sink_done 后 `$finish`、超时保护
4. **寄存器配置必须用 `reg_config` BFM**（`sim/common/reg_config.v`，读
   `sim/testdata/regcfg.hex`），cfg_* 信号声明为 wire 接到 BFM 输出；
   仿真控制台运行时会按界面上编辑的寄存器值生成 regcfg.hex
5. `axis_video_source` 的 `enable` 端口必须接 `reg_config` 的 `done`
   （保证寄存器配置完成后视频流才启动）；无寄存器的 IP 接 `1'b1`

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
    .cfg_wen(cfg_wen), .cfg_ren(cfg_ren), .done(cfg_done));

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

## 编码规范

- 纯 Verilog-2001（iverilog -g2012 可编译），不用 SystemVerilog 类/接口
- 时序逻辑统一 `always @(posedge aclk)`，复位用同步判断 `if (!aresetn)`
- 命名：模块/信号小写下划线，参数 `C_` 前缀大写
- 流水线设计目标 125MHz，1 像素/时钟吞吐

## 验证闭环（生成代码后必须执行）

```bash
make all IP=<ip_name> WIDTH=64 HEIGHT=48   # 全流程: 激励→仿真→还原→分析
```

**统计类 IP 必须用多帧验证**：自动白平衡、自动对比度等依赖帧统计的 IP，
增益/参数在第 N 帧统计、第 N+1 帧才生效，单帧仿真输出必然等于输入。
此类 IP 验证时必须 `FRAMES=2`（或更多），分析工具默认取最后一帧：

```bash
make all IP=auto_white_balance WIDTH=64 HEIGHT=48 FRAMES=2
```

完成此类 IP 后，提醒用户在仿真控制台把"帧数"设为 2 以上。

### 需要"整帧/上一帧"的 IP 用 DDR 帧缓冲

区分两类帧间需求：
- **只需统计量**（AWB 的累加和、对比度的直方图）→ 片上寄存器，不用 DDR
- **需上一帧全部像素**（时域降噪、帧平均、运动检测、帧率转换）→ 用片外 DDR 帧缓冲

后者例化 `sim/common/axi_frame_buffer.v` + `sim/common/ddr_model.v`（标准 AXI4，
**勿改这两个公共模块**）。帧缓冲对外是简单的"写帧流 wr_*/读上一帧流 rd_*"，
IP 把当前帧写入、同时消费 rd 端的上一帧像素做处理（读写 1:1 配速）。
`prev_valid` 首帧为 0（无上一帧时直通）。详见 `docs/IP_SPEC_ddr_frame_buffer.md`。
DDR 规格（位宽/容量/延迟）可按 IP 需求调参。

### 金标准模型（强烈建议为每个 IP 配套）

`scripts/golden.py` 用 Python 按位复现各 IP 的定点运算，逐字比对仿真结果给出
PASS/FAIL（`make verify IP=<ip>`，控制台运行后也会显示金标准徽章）。新增 IP 时
应在 `golden.py` 加一个模型函数并注册：

1. 在 `MODELS` 加 `'<ip>': m_<ip>`，在 `CONFIG` 加 `{frames, tol, frac}`
2. 模型读 `regcfg.hex` 的寄存器写序列（`final_regs`），复现 RTL 的**整数/定点**
   运算：算术右移用 `np.right_shift`（对负数=向下取整，等价 Verilog `>>>`）；
   截断/饱和/舍入规则必须与 RTL 完全一致
3. 无状态 IP（查表/逐像素/窗口）应做到容差 0 逐位精确；含帧内瞬态的统计类 IP
   （如除法延迟）用 `tol`/`frac` 容许少量失配，并在注释说明原因
4. 窗口类 IP 的邻居用 `neighbors()`（边界复制 = RTL 镜像），与 RTL 对齐规则一致

## 自定义图像/视频预处理（用户用自然语言驱动）

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

## 实战经验教训（来自真实 IP 调试，生成代码时必须遵守）

以下问题在本环境中实际发生过，每条都导致过仿真失败或图像损坏：

### 1. 窗口类 IP（3×3 卷积/锐化/降噪）的对齐规则

- **tuser/tlast 必须跟随中心像素走流水线**，不得直接透传输入的标记
  （否则输出内容与坐标错开，整图错位，且每帧末行丢失）
- **列计数器必须每行清零**（SOF *和* 行尾后都要清零），列号才是行缓冲的
  正确地址；只在 SOF 清零会变成"全帧像素序号"，窗口数据全错
- 行尾/帧尾必须冲刷：用边界镜像补缺失的邻居，保证**每帧输出像素数
  严格等于输入**（否则 sink 等不齐数据，仿真挂死）
- 边界（首行/首列/末列）用镜像/复制，不得读行缓冲中的跨帧残留数据

### 2. 统计类 IP（AWB/直方图均衡）的乒乓缓冲模式

- 帧与帧之间**没有空闲周期**（视频流背靠背），任何"帧间计算"都必须
  后台进行：统计数组、结果 LUT 都要**双缓冲乒乓**
  （帧 N 统计 → 帧 N+1 后台构建+清零旧统计 → 帧 N+2 切换生效）
- 归一化除法不得按分辨率硬编码系数（如 `×85>>10` 只对 64×48 成立），
  用 30~40 拍的串行移位减法除法器现算倒数
- SOF 拍翻转的状态（lut_valid/lut_sel 等）：SOF 像素本身读到的还是
  旧值（非阻塞赋值），需组合前馈让首像素用切换后的新值

### 3. 仿真数组初始化

- 所有 reg 数组（直方图、行缓冲、LUT、系数表）必须加 `initial` 块初始化，
  否则 X 态会传染（`X+1=X`），整帧输出变成 `00xxxxxx`
- 算法上能用边界镜像替代"读未写过的存储"时优先用镜像
- **不要用 `assign` 连续赋值去读 reg 数组**（如 `assign y = f(coef[i])`，
  f 内部读模块级 memory）：iverilog 对"函数/连续赋值读 memory 数组"不建立
  敏感性，时刻 0 读到 X 后永不重算、X 卡死；且运行时改数组值不会重新求值。
  正确做法：把读数组的运算放进 `always @(posedge aclk)` 时钟块内调用（每拍
  重算，读当前值）。色彩空间转换的矩阵系数表踩过此坑。

### 4. AXI-Stream 握手细则

- `m_axis_tvalid` 一旦拉高，必须保持到 `m_axis_tready` 接受后才允许
  变化；输出寄存器只在 `!m_axis_tvalid || m_axis_tready` 时更新
- 简单 1 进 1 出 IP 的标准写法：`assign s_axis_tready = !m_axis_tvalid || m_axis_tready`
- 生成后必须用随机反压复测：
  `iverilog -g2012 -Ptb_<ip>.C_READY_MODE=1 ...`，像素不得丢失或重复

- 仿真日志出现 `PASS: 仿真完成` 且无 `ERROR:` 才算通过
- 算法效果通过仿真控制台的分析面板验证（锐度/白平衡/直方图/PSNR）
- 修改代码后重新运行上述命令直到通过
