#!/usr/bin/env python3
"""gen_ip_spec.py — 从 .ip_spec.yaml 生成完整的 IP 包

生成物：
  rtl/<ip>/<ip>.v          Verilog RTL
  rtl/<ip>/regdef.json     寄存器描述
  sim/tests/tb_<ip>.v      Testbench 骨架
  scripts/golden.py         金标准函数（追加 / 替换）

用法：
  # 从 spec 文件生成（命令行）
  python scripts/gen_ip_spec.py --spec specs/my_filter.yaml

  # 从 Trae 扩展调用（AI 驱动）
  python scripts/gen_ip_spec.py --name my_filter --algo "sharpen" --regs "CTRL,bypass"

  # 从 AI 自然语言描述生成
  python scripts/gen_ip_spec.py --prompt "实现一个3x3锐化滤波器，系数[1,-2,1]，支持bypass"

  # 生成级联组合 IP（金标准 + regdef + TB）
  python scripts/gen_ip_spec.py --chain awb,gamma,sharpen

  # 注册级联组合到 golden.py（金标准自动对接）
  python scripts/gen_ip_spec.py --register-chain awb_gamma_sharpen --chain awb,gamma,sharpen
"""
import argparse
import os
import re
import sys
import json
import shutil
import subprocess

# ─────────────────────────────────────────────────────────────────────────────
# 1. YAML 解析（纯标准库实现，不依赖 pyyaml）
# ─────────────────────────────────────────────────────────────────────────────

def parse_yaml(text):
    """极简 YAML parser：支持嵌套 dict / list / 标量 (按缩进解析)"""
    lines = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith('#'):
            continue
        indent = len(raw) - len(raw.lstrip(' '))
        lines.append([indent, stripped])

    pos = [0]
    key_re = re.compile(r'^(\w[\w_]*)\s*:\s*(.*)$')

    def parse_node(indent):
        return (parse_list(indent) if lines[pos[0]][1].startswith('- ')
                else parse_map(indent))

    def parse_map(indent):
        d = {}
        while pos[0] < len(lines) and lines[pos[0]][0] == indent:
            content = lines[pos[0]][1]
            if content.startswith('- '):
                break  # 同缩进的 list 项不属于当前 map
            m = key_re.match(content)
            if not m:
                break
            key, val = m.group(1), m.group(2).strip()
            pos[0] += 1
            if val != '':
                d[key] = _parse_value(val)
            elif pos[0] < len(lines) and lines[pos[0]][0] > indent:
                d[key] = parse_node(lines[pos[0]][0])          # 更深缩进的子块
            elif (pos[0] < len(lines) and lines[pos[0]][0] == indent
                  and lines[pos[0]][1].startswith('- ')):
                d[key] = parse_list(indent)                    # 同缩进的列表
            else:
                d[key] = {}
        return d

    def parse_list(indent):
        arr = []
        while (pos[0] < len(lines) and lines[pos[0]][0] == indent
               and lines[pos[0]][1].startswith('- ')):
            rest = lines[pos[0]][1][2:].strip()
            # 把 "- " 折成 indent+2 处的首行, 余下同缩进行归属同一元素
            lines[pos[0]] = [indent + 2, rest]
            if key_re.match(rest):
                arr.append(parse_map(indent + 2))
            else:
                arr.append(_parse_value(rest))
                pos[0] += 1
        return arr

    if not lines:
        return {}
    return parse_node(lines[0][0])


def _parse_value(val):
    if not val:
        return {}
    # bool / null
    if val in ('true', 'True'): return True
    if val in ('false', 'False'): return False
    if val in ('null', '~'): return None
    # number
    if re.match(r'^-?\d+$', val): return int(val)
    if re.match(r'^-?\d+\.\d+$', val): return float(val)
    # unquoted string
    if val in ('{', '}'): return val
    return val.strip('"\'')


def load_spec(path):
    with open(path) as f:
        text = f.read()
    spec = parse_yaml(text)
    # 展平 include
    if 'includes' in spec:
        included = []
        for inc in spec['includes']:
            inc_path = os.path.join(os.path.dirname(path), inc['spec'])
            included.append(load_spec(inc_path))
        spec['includes'] = included
    return spec


# ─────────────────────────────────────────────────────────────────────────────
# 2. 代码生成器
# ─────────────────────────────────────────────────────────────────────────────

def _snake(name):
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


def _capitalize(name):
    return ''.join(x.capitalize() for x in _snake(name).split('_'))


def _c_array(name):
    """转 C_SNAKE 格式"""
    return 'C_' + _snake(name).upper()


# ── 2a. Verilog RTL ──────────────────────────────────────────────────────────

def _gen_kernel_logic(spec):
    """生成窗口处理核心逻辑（返回值是普通字符串，不用 f-string）"""
    algo = spec.get('algorithm', {})
    typ = algo.get('type', 'passthrough')
    kernel = algo.get('kernel', [1])

    if typ == 'passthrough':
        return "assign kernel_tdata = s_axis_tdata;"

    elif typ == 'gain':
        # out = (pixel * gain) >> 8, 饱和到 255 (与 golden 的整数定点一致)
        return (
            "wire [23:0] mul_r = s_axis_tdata[23:16] * reg_10[15:0];\n"
            "wire [23:0] mul_g = s_axis_tdata[15: 8] * reg_10[15:0];\n"
            "wire [23:0] mul_b = s_axis_tdata[ 7: 0] * reg_10[15:0];\n"
            "wire [15:0] sh_r = mul_r[23:8];\n"
            "wire [15:0] sh_g = mul_g[23:8];\n"
            "wire [15:0] sh_b = mul_b[23:8];\n"
            "wire [7:0] out_r = |sh_r[15:8] ? 8'd255 : sh_r[7:0];\n"
            "wire [7:0] out_g = |sh_g[15:8] ? 8'd255 : sh_g[7:0];\n"
            "wire [7:0] out_b = |sh_b[15:8] ? 8'd255 : sh_b[7:0];\n"
            "assign kernel_tdata = {8'b0, out_r, out_g, out_b};"
        )

    elif typ == 'conv_1d':
        k_str = ','.join(str(x) for x in kernel)
        # 像素零扩展为 9 位有符号正数, 支持负系数 (NOTE: 此 RTL 把 R/G/B 当作
        # 三个抽头, 与 golden 的空间邻域卷积不一致 — conv_1d 暂不保证逐位对齐)
        ext = "{1'b0, s_axis_tdata[23:16]}"
        extg = "{1'b0, s_axis_tdata[15: 8]}"
        ext2 = "{1'b0, s_axis_tdata[ 7: 0]}"
        shift = algo.get('fixed_point', {}).get('shift', 0)
        return (
            "// 1D 卷积 kernel=[" + k_str + "], shift=" + str(shift) + "\n"
            "wire signed [17:0] acc =\n"
            "    $signed(" + ext + ") * " + str(kernel[0]) + " +\n"
            "    $signed(" + extg + ") * " + str(kernel[1]) + " +\n"
            "    $signed(" + ext2 + ") * " + str(kernel[2]) + ";\n"
            "wire [17:0] acc18 = acc >>> " + str(shift) + ";\n"
            "wire [7:0] out_r = acc18[17:10];\n"
            "assign kernel_tdata = {8'b0, out_r, s_axis_tdata[15:0]};"
        )
    elif typ == 'csc':
        coef = algo.get('coef', [77, 150, 29, -43, -85, 128, 128, -107, 21])
        off_r, off_g, off_b = algo.get('offset', [0, 128, 128])
        assign = f"""// 色彩空间转换矩阵
wire signed [17:0] tmp_y  = $signed(s_axis_tdata[23:16]) * {coef[0]}
                              + $signed(s_axis_tdata[15: 8]) * {coef[1]}
                              + $signed(s_axis_tdata[ 7: 0]) * {coef[2]} + {off_r*256};
wire signed [17:0] tmp_u  = $signed(s_axis_tdata[23:16]) * {coef[3]}
                              + $signed(s_axis_tdata[15: 8]) * {coef[4]}
                              + $signed(s_axis_tdata[ 7: 0]) * {coef[5]} + {off_g*256};
wire signed [17:0] tmp_v  = $signed(s_axis_tdata[23:16]) * {coef[6]}
                              + $signed(s_axis_tdata[15: 8]) * {coef[7]}
                              + $signed(s_axis_tdata[ 7: 0]) * {coef[8]} + {off_b*256};
wire signed [17:0] sat_y = (tmp_y >>> 8) + {off_r};
wire signed [17:0] sat_u = (tmp_u >>> 8) + {off_g};
wire signed [17:0] sat_v = (tmp_v >>> 8) + {off_b};
assign kernel_tdata = {{8'b0,
    sat_y[7] ? 8'd0 : sat_y[17] ? 8'd255 : sat_y[7:0],
    sat_u[7] ? 8'd0 : sat_u[17] ? 8'd255 : sat_u[7:0],
    sat_v[7] ? 8'd0 : sat_v[17] ? 8'd255 : sat_v[7:0]}};"""
    else:
        assign = 'assign kernel_tdata = s_axis_tdata;  // TODO: implement algorithm'
    return assign


def _gen_reg_decl(spec):
    regs = spec.get('registers', [])
    decl = []
    for r in regs:
        name = r['name'].upper()
        decl.append(f"reg [31:0] reg_{r['addr'].replace('0x','')};")
    return '\n'.join(decl)


def _gen_reg_logic(spec):
    """cfg_wen 有效时的寄存器写解码 (每行无缩进, 块缩进由调用方加)。"""
    regs = spec.get('registers', [])
    body = []
    for r in regs:
        a = r['addr'][2:]
        body.append(f"if (cfg_addr == 8'h{a.upper()}) reg_{a.lower()} <= cfg_wdata;")
    return '\n'.join(body)


def _gen_reg_reset(spec):
    """复位时把寄存器置为 spec 缺省值 (每行无缩进)。"""
    regs = spec.get('registers', [])
    body = []
    for r in regs:
        a = r['addr'][2:]
        dv = r.get('default', '0x0')
        dv = dv[2:] if dv.lower().startswith('0x') else dv
        body.append(f"reg_{a.lower()} <= 32'h{int(dv, 16):08x};")
    return '\n'.join(body)


def _gen_ctrl_logic(spec):
    regs = spec.get('registers', [])
    for r in regs:
        if r.get('name','').upper() in ('CTRL', 'CONTROL'):
            return f"wire enable = reg_{r['addr'].replace('0x','')}[0];\nwire bypass = reg_{r['addr'].replace('0x','')}[1];"
    return 'wire enable = 1\'b1;\nwire bypass = 1\'b0;'


def generate_verilog(spec):
    ip = spec['name']
    snake = _snake(ip)
    cap = _capitalize(ip)
    algo = spec.get('algorithm', {})
    typ = algo.get('type', 'passthrough')
    latency = spec.get('pipeline', {}).get('latency', 1)
    regs = spec.get('registers', [])

    reg_decl = _gen_reg_decl(spec)
    reg_logic = _gen_reg_logic(spec)
    ctrl = _gen_ctrl_logic(spec)
    kernel = _gen_kernel_logic(spec)
    has_regs = bool(regs)

    # tuser/tlast 透传
    if latency > 1:
        tuser_pipe = ("reg tuser_pipe;\n"
                      "always @(posedge aclk) if (m_axis_tvalid) tuser_pipe <= s_axis_tuser;\n"
                      "assign m_axis_tuser = tuser_pipe;")
        tlast_pipe = ("reg tlast_pipe;\n"
                       "always @(posedge aclk) if (m_axis_tvalid) tlast_pipe <= s_axis_tlast;\n"
                       "assign m_axis_tlast = tlast_pipe;")
    else:
        tuser_pipe = "assign m_axis_tuser = s_axis_tuser;"
        tlast_pipe = "assign m_axis_tlast = s_axis_tlast;"

    # 寄存器接口声明
    if has_regs:
        reg_iface = ("  // Register interface\n"
                     "  input  [ 7:0] cfg_addr,\n"
                     "  input  [31:0] cfg_wdata,\n"
                     "  input         cfg_wen,\n"
                     "  input         cfg_ren,\n"
                     "  output reg[31:0] cfg_rdata\n")
    else:
        reg_iface = ("  // Register interface (stub — add registers in spec)\n"
                     "  input  [ 7:0] cfg_addr,\n"
                     "  input  [31:0] cfg_wdata,\n"
                     "  input         cfg_wen,\n"
                     "  input         cfg_ren,\n"
                     "  output reg[31:0] cfg_rdata\n")

    # 寄存器配置块: 复位置缺省值, cfg_wen 有效时按地址写入
    reg_reset = _gen_reg_reset(spec)
    if reg_logic.strip():
        ind = lambda s: '\n'.join('      ' + l for l in s.splitlines())
        reg_init_block = (
            "\n  always @(posedge aclk) begin\n"
            "    if (!aresetn) begin\n" + ind(reg_reset) + "\n"
            "    end else if (cfg_wen) begin\n" + ind(reg_logic) + "\n"
            "    end\n  end\n")
    else:
        reg_init_block = ""

    cap_lat = "C_" + cap.upper() + "_LAT"
    body = (
        "`timescale 1ns / 1ps\n"
        "// =============================================================================\n"
        "// {ip} — Auto-generated from .ip_spec.yaml\n"
        "// Algorithm: {typ}  |  Latency: {lat} cycle(s)\n"
        "// =============================================================================\n\n"
        "module {cap}\n"
        "#(parameter {cap_lat} = {lat})\n"
        "(\n"
        "  input aclk, input aresetn,\n\n"
        "  // AXI-Stream slave\n"
        "  input      s_axis_tvalid,\n"
        "  output reg s_axis_tready,\n"
        "  input [31:0] s_axis_tdata,\n"
        "  input      s_axis_tuser,\n"
        "  input      s_axis_tlast,\n\n"
        "  // AXI-Stream master\n"
        "  output reg m_axis_tvalid,\n"
        "  input      m_axis_tready,\n"
        "  output reg[31:0] m_axis_tdata,\n"
        "  output reg m_axis_tuser,\n"
        "  output reg m_axis_tlast,\n"
        "{reg_iface}"
        ");\n\n"
        "  // ── Register file ─────────────────────────────────────────────────────────\n"
        "{reg_decl}\n"
        "{reg_init_block}"
        "  // ── Control signals ────────────────────────────────────────────────────────\n"
        "{ctrl}\n\n"
        "  // ── Data path ─────────────────────────────────────────────────────────────\n"
        "  wire [31:0] kernel_tdata;\n"
        "{kernel}\n\n"
        "  // ── tuser/tlast 透传 (latency={lat}) ─────────────────────────────────\n"
        "{tuser}\n"
        "{tlast}\n\n"
        "  // ── Ready/Valid handshake ───────────────────────────────────────────────\n"
        "  always @(*) s_axis_tready = !m_axis_tvalid || m_axis_tready;\n\n"
        "  always @(posedge aclk) begin\n"
        "    if (!aresetn) begin\n"
        "      m_axis_tvalid <= 1'b0;\n"
        "      m_axis_tdata  <= 32'b0;\n"
        "    end else if (bypass) begin\n"
        "      m_axis_tvalid <= s_axis_tvalid;\n"
        "      m_axis_tdata  <= s_axis_tdata;\n"
        "    end else begin\n"
        "      m_axis_tvalid <= s_axis_tvalid;\n"
        "      m_axis_tdata  <= kernel_tdata;\n"
        "    end\n"
        "  end\n\n"
        "endmodule\n"
    ).format(
        ip=ip, typ=typ, lat=latency, cap=cap,
        cap_lat=cap_lat,
        reg_iface=reg_iface,
        reg_decl=reg_decl,
        reg_init_block=reg_init_block,
        ctrl=ctrl,
        kernel=kernel,
        tuser=tuser_pipe,
        tlast=tlast_pipe,
    )
    return body


# ── 2b. regdef.json ─────────────────────────────────────────────────────────

def generate_regdef(spec):
    ip = spec['name']
    regs = spec.get('registers', [])
    includes = spec.get('includes', [])
    out = {}
    if includes:
        out['includes'] = includes
    out['registers'] = []
    for r in regs:
        out['registers'].append({
            'addr': r['addr'],
            'name': r['name'].upper(),
            'access': r.get('access', 'RW'),
            'default': r.get('default', '0x00000000'),
            'desc': r.get('desc', '')
        })
    return json.dumps(out, indent=2, ensure_ascii=False)


# ── 2c. Testbench ───────────────────────────────────────────────────────────

def generate_tb(spec):
    ip = spec['name']
    cap = _capitalize(ip)
    return f"""`timescale 1ns / 1ps
// tb_{ip}.v — Auto-generated, replace/improve as needed
module tb_{ip};

parameter C_WIDTH  = 64;
parameter C_HEIGHT = 48;
parameter C_FRAMES = 1;
parameter C_STREAM = 0;
parameter C_DATA_WIDTH = 32;
parameter C_STIMULUS_FILE = "sim/testdata/stimulus.hex";
parameter C_RESULT_FILE   = "sim/testdata/result.hex";
parameter C_READY_MODE = 0;

reg aclk = 1'b0;  always #4 aclk = ~aclk;
reg aresetn = 1'b0;

wire        src_tvalid, src_tready, src_tuser, src_tlast;
wire [31:0] src_tdata;
wire        dut_tvalid, dut_tready, dut_tuser, dut_tlast;
wire [31:0] dut_tdata;
wire        src_done, sink_done;
wire [31:0] src_cnt, sink_cnt;

wire [ 7:0] cfg_addr;  wire [31:0] cfg_wdata;
wire        cfg_wen, cfg_ren, cfg_done;
wire [31:0] cfg_rdata;

reg_config u_regcfg (.aclk, .aresetn,
    .cfg_addr, .cfg_wdata, .cfg_wen, .cfg_ren, .cfg_rdata, .done(cfg_done));

axis_video_source #(
    .C_DATA_WIDTH(C_DATA_WIDTH), .C_WIDTH(C_WIDTH), .C_HEIGHT(C_HEIGHT),
    .C_FRAMES(C_FRAMES), .C_STREAM(C_STREAM),
    .C_STIMULUS_FILE(C_STIMULUS_FILE)
) u_src (.aclk, .aresetn, .enable(cfg_done),
    .m_axis_tvalid(src_tvalid), .m_axis_tready(src_tready),
    .m_axis_tdata(src_tdata), .m_axis_tuser(src_tuser), .m_axis_tlast(src_tlast),
    .frame_done(src_done), .pixel_cnt(src_cnt));

{cap} u_dut (.aclk, .aresetn,
    .s_axis_tvalid(src_tvalid), .s_axis_tready(src_tready),
    .s_axis_tdata(src_tdata),  .s_axis_tuser(src_tuser), .s_axis_tlast(src_tlast),
    .m_axis_tvalid(dut_tvalid),.m_axis_tready(dut_tready),
    .m_axis_tdata(dut_tdata),  .m_axis_tuser(dut_tuser), .m_axis_tlast(dut_tlast),
    .cfg_addr(cfg_addr), .cfg_wdata(cfg_wdata), .cfg_wen(cfg_wen),
    .cfg_ren(cfg_ren),  .cfg_rdata(cfg_rdata));

axis_video_sink #(
    .C_DATA_WIDTH(C_DATA_WIDTH), .C_WIDTH(C_WIDTH), .C_HEIGHT(C_HEIGHT),
    .C_FRAMES(C_FRAMES), .C_READY_MODE(C_READY_MODE),
    .C_RESULT_FILE(C_RESULT_FILE)
) u_snk (.aclk, .aresetn,
    .s_axis_tvalid(dut_tvalid),.s_axis_tready(dut_tready),
    .s_axis_tdata(dut_tdata),  .s_axis_tuser(dut_tuser), .s_axis_tlast(dut_tlast),
    .frame_done(sink_done), .pixel_cnt(sink_cnt));

initial if ($test$plusargs("WAVE")) begin
    $dumpfile("output/waves/{ip}.vcd");
    $dumpvars(0, tb_{ip});
end

initial begin
    repeat(10) @(posedge aclk);  aresetn = 1'b1;
    wait(sink_done);
    repeat(10) @(posedge aclk);
    $display("PASS: %0d pixels received (%0dx%0d x %0d frames)", sink_cnt, C_WIDTH, C_HEIGHT, C_FRAMES);
    $finish;
end

initial begin
    #(C_WIDTH * C_HEIGHT * C_FRAMES * 8 * 100 + 500_000);
    $display("ERROR: timeout");  $finish;
end

endmodule
"""


# ── 2d. 金标准 Python 函数 ───────────────────────────────────────────────────

def _np_shift(val, bits):
    """Python 算术右移（与 Verilog >>> 等价）"""
    if bits == 0:
        return 'np.int64({val})'
    return f'np.right_shift(np.int64({val}), {bits})'


def generate_golden_func(spec):
    """从 spec 生成 golden.py 中的函数体（字符串，供追加到 golden.py）"""
    ip = spec['name']
    snake = _snake(ip)
    algo = spec.get('algorithm', {})
    typ = algo.get('type', 'passthrough')
    regs_spec = spec.get('registers', [])
    shift = algo.get('fixed_point', {}).get('shift', 0)
    kernel = algo.get('kernel', [])
    coef = algo.get('coef', [77, 150, 29, -43, -85, 128, 128, -107, 21])

    # 寄存器默认值映射
    reg_defaults = {}
    for r in regs_spec:
        reg_defaults[eval('0x' + r['addr'].replace('0x',''))] = eval(r.get('default', '0x0').replace('0x','0x'))
    # 整数键/整数值的 Python 字面量, 供 final_regs() 与后续 regs.get(0xNN) 整数查表匹配
    # (用 json 会得到字符串键, 整数地址永远查不中, 导致 spec 寄存器缺省值被静默忽略)
    defaults_str = '{' + ', '.join(
        f'0x{k:02X}: 0x{v:08X}' for k, v in sorted(reg_defaults.items())) + '}'

    lines = [
        f"def m_{snake}(fr, writes, fi, st):",
        f"    regs = final_regs(writes, {defaults_str})",
        f"    enable = regs.get(0x04, 0x1) & 1",
        f"    bypass = (regs.get(0x04, 0x1) >> 1) & 1",
        f"    if not enable or bypass:",
        f"        return fr.copy()",
    ]

    if typ == 'passthrough':
        lines.append("    return fr.copy()")

    elif typ == 'gain':
        # (pixel * gain) >> 8, 饱和 — 与 RTL 整数定点逐位一致
        lines.append(f"    k = regs.get(0x10, 0x100) & 0xFFFF")
        lines.append(f"    return clamp8(np.right_shift(fr * np.int64(k), 8))")

    elif typ == 'lut':
        lines.append("    lut = np.arange(256, dtype=np.int64)")
        lines.append("    # TODO: fill lut according to your LUT spec")
        lines.append("    return lut[fr]")

    elif typ == 'conv_1d' and len(kernel) == 3:
        k0, k1, k2 = kernel
        lines.append(f"    # conv_1d kernel={kernel}, shift={shift}")
        lines.append(f"    C = fr.astype(np.int64)")
        lines.append(f"    N = np.roll(C, 1, axis=0); N[0,:,:] = C[0,:,:]  # 镜像")
        lines.append(f"    E = np.roll(C, 1, axis=1); E[:,0,:] = C[:,0,:]  # 镜像")
        lines.append(f"    acc = {k0}*N + {k1}*C + {k2}*E")
        lines.append(f"    acc = np.right_shift(acc, {shift})")
        lines.append("    return clamp8(acc)")

    elif typ == 'csc':
        lines.append(f"    M = np.array({coef}, dtype=np.int64).reshape(3,3)")
        lines.append(f"    O = np.array({algo.get('offset',[0,128,128])}, dtype=np.int64)")
        lines.append("    flat = fr.reshape(-1, 3)")
        lines.append("    acc = flat @ M.T")
        lines.append("    sh = np.right_shift(acc, 8) + O")
        lines.append("    return clamp8(sh).reshape(fr.shape)")

    elif typ == 'sharpen':
        k = algo.get('sharpen_factor', 4)
        lines.append(f"    # sharpen factor={k}")
        lines.append(f"    C = fr.astype(np.int64)")
        lines.append(f"    N = np.roll(C, 1, axis=0); N[0,:,:]=C[0,:,:]")
        lines.append(f"    E = np.roll(C, 1, axis=1); E[:,0,:]=C[:,0,:]")
        lines.append(f"    lap = 4*C - 2*N - E")
        lines.append(f"    out = C + np.right_shift(lap * {k}, 3)")
        lines.append("    return clamp8(out)")

    elif typ == 'denoise':
        k = algo.get('strength', 4)
        lines.append(f"    # denoise strength={k}")
        lines.append(f"    C = fr.astype(np.int64)")
        lines.append(f"    N = np.roll(C, 1, axis=0); N[0,:,:]=C[0,:,:]")
        lines.append(f"    E = np.roll(C, 1, axis=1); E[:,0,:]=C[:,0,:]")
        lines.append(f"    filt = np.right_shift(4*C + 2*N + E, 3)")
        lines.append(f"    out = C + np.right_shift((filt - C) * {k}, 3)")
        lines.append("    return clamp8(out)")

    else:
        lines.append("    # TODO: implement algorithm for type=" + typ)
        lines.append("    return fr.copy()")

    return '\n'.join(lines)


def generate_golden_config(spec):
    """生成 golden.py CONFIG 条目"""
    ip = spec['name']
    snake = _snake(ip)
    latency = spec.get('pipeline', {}).get('latency', 1)
    frames = max(1, latency)
    return f"    '{snake}':        {{'frames': {frames}, 'tol': 0, 'frac': 0.0}},"


# ─────────────────────────────────────────────────────────────────────────────
# 3. 文件写入
# ─────────────────────────────────────────────────────────────────────────────

def write_all(spec, dry_run=False):
    ip = spec['name']
    snake = _snake(ip)

    rtl_dir = os.path.join('rtl', snake)
    sim_dir = os.path.join('sim', 'tests')
    if not dry_run:
        os.makedirs(rtl_dir, exist_ok=True)
        os.makedirs(sim_dir, exist_ok=True)

    # RTL
    rtl_content = generate_verilog(spec)
    rtl_path = os.path.join(rtl_dir, f'{snake}.v')
    print(f"  RTL      → {rtl_path}")
    if not dry_run:
        with open(rtl_path, 'w') as f: f.write(rtl_content)

    # regdef.json
    regdef_content = generate_regdef(spec)
    regdef_path = os.path.join(rtl_dir, 'regdef.json')
    print(f"  regdef   → {regdef_path}")
    if not dry_run:
        with open(regdef_path, 'w') as f: f.write(regdef_content)

    # Testbench
    tb_content = generate_tb(spec)
    tb_path = os.path.join(sim_dir, f'tb_{snake}.v')
    print(f"  TB       → {tb_path}")
    if not dry_run:
        with open(tb_path, 'w') as f: f.write(tb_content)

    # golden.py 追加
    golden_func = generate_golden_func(spec)
    golden_cfg = generate_golden_config(spec)
    golden_path = 'scripts/golden.py'

    func_name = f"m_{snake}"
    cfg_key = f"'{snake}'"

    if not dry_run:
        # 读取现有 golden.py
        if os.path.exists(golden_path):
            with open(golden_path) as f:
                content = f.read()
        else:
            content = (
                '#!/usr/bin/env python3\n'
                '"""golden.py — 各 IP 的按位精确金标准模型"""\n'
                'import argparse, numpy as np\n\nMODELS = {}\nCONFIG = {}\n\n'
            )

        # 检查是否已有该模型，有则替换，无则追加
        pattern = rf'def {func_name}\(fr, writes, fi, st\):.*?(?=\n\ndef |\nMODELS =|\Z)'
        if re.search(pattern, content, re.DOTALL):
            content = re.sub(pattern, golden_func + '\n', content, flags=re.DOTALL)
            print(f"  golden   → {golden_path} (替换已有模型)")
        else:
            # 必须插在 MODELS 字典之前 — MODELS 在 import 时求值并引用该函数,
            # 追加到文件末尾会导致 NameError
            content = content.replace(
                'MODELS = {', golden_func + '\n\n\nMODELS = {', 1)
            print(f"  golden   → {golden_path} (追加新模型)")

        # 注册到 MODELS
        if f"'{snake}':" not in content.split('MODELS')[1].split('CONFIG')[0]:
            mod_str = f"    '{snake}': {func_name},"
            content = content.replace(
                'MODELS = {',
                f"MODELS = {{\n{mod_str}"
            )

        # 注册到 CONFIG
        cfg_pattern = rf"CONFIG = \{{[^}}]*'{snake}'"
        if not re.search(cfg_pattern, content):
            cfg_str = golden_cfg
            content = content.replace(
                'CONFIG = {',
                f"CONFIG = {{\n{cfg_str}"
            )

        with open(golden_path, 'w') as f: f.write(content)

    print(f"\n✅ IP '{ip}' 生成完成!")
    print(f"   运行验证: make verify IP={snake} WIDTH=64 HEIGHT=48")
    return snake


# ─────────────────────────────────────────────────────────────────────────────
# 4. 级联组合生成
# ─────────────────────────────────────────────────────────────────────────────

def generate_chain_rtl(ip_names, name=None):
    """生成级联组合 IP 的 RTL（上游 → 下游直连）"""
    chain_name = name or '_'.join(ip_names)
    chain_cap = _capitalize(chain_name)
    instances = []
    wires = []
    for i, ip in enumerate(ip_names):
        cap = _capitalize(ip)
        s2m = []
        for sig in ('tvalid', 'tready', 'tdata', 'tuser', 'tlast'):
            w = f"wire       {sig}_{i}" if sig == 'tvalid' or sig == 'tready' or sig == 'tuser' or sig == 'tlast' else f"wire [31:0] {sig}_{i}"
            wires.append(w)
            s2m.append(f" .{sig}({sig}_{i})")
        if i == 0:
            src_wires = s2m[:]
        else:
            dst_wires = s2m[:]
        instances.append(f"""  {cap} u_{ip} (
    .aclk(aclk), .aresetn(aresetn),
    .s_axis_tvalid({"s_axis_tvalid" if i==0 else f"{'tvalid'}_{i-1}"}),
    .s_axis_tready({"s_axis_tready" if i==0 else f"{'tready'}_{i-1}"}),
    .s_axis_tdata ({"s_axis_tdata"  if i==0 else f"{'tdata'}_{i-1}"}),
    .s_axis_tuser ({"s_axis_tuser"  if i==0 else f"{'tuser'}_{i-1}"}),
    .s_axis_tlast ({"s_axis_tlast"  if i==0 else f"{'tlast'}_{i-1}"}),
    .m_axis_tvalid({f"{'tvalid'}_{i}"}), .m_axis_tready({f"{'tready'}_{i}"}),
    .m_axis_tdata ({f"{'tdata'}_{i}"}),  .m_axis_tuser ({f"{'tuser'}_{i}"}),
    .m_axis_tlast ({f"{'tlast'}_{i}"}),
    .cfg_addr(cfg_addr), .cfg_wdata(cfg_wdata), .cfg_wen(cfg_wen),
    .cfg_ren(cfg_ren),  .cfg_rdata(cfg_rdata)  // 共享寄存器接口
  );""")

    last = len(ip_names) - 1
    wire_decls = '\n'.join(wires)
    instance_blk = '\n'.join(instances)
    chain_list = ' → '.join(ip_names)
    return f"""`timescale 1ns / 1ps
// {chain_cap} — 级联组合 IP: {chain_list}
module {chain_cap} (
  input aclk, input aresetn,
  input s_axis_tvalid, output s_axis_tready, input[31:0] s_axis_tdata,
  input s_axis_tuser, input s_axis_tlast,
  output m_axis_tvalid, input m_axis_tready, output[31:0] m_axis_tdata,
  output m_axis_tuser, output m_axis_tlast,
  input[7:0] cfg_addr, input[31:0] cfg_wdata, input cfg_wen, cfg_ren,
  output[31:0] cfg_rdata
);
{wire_decls}
{instance_blk}
  assign m_axis_tvalid = tvalid_{last};
  assign m_axis_tdata  = tdata_{last};
  assign m_axis_tuser  = tuser_{last};
  assign m_axis_tlast  = tlast_{last};
  assign tready_{last} = m_axis_tready;
  assign s_axis_tready = !tvalid_0 || tready_0;
endmodule
"""


def generate_chain_regdef(ip_names, name=None):
    """生成级联组合 IP 的 regdef.json（合并子 IP 的寄存器表）"""
    chain_name = name or '_'.join(ip_names)
    chain_cap = _capitalize(chain_name)
    includes = []
    offset = 0
    for ip in ip_names:
        regdef_path = f'rtl/{ip}/regdef.json'
        prefix = _snake(ip).upper() + '_'
        includes.append({
            'ip': ip,
            'base': f'0x{offset:02X}',
            'prefix': prefix,
            'spec': regdef_path
        })
        offset += 0x40
    return json.dumps({'includes': includes, 'registers': []}, indent=2, ensure_ascii=False)


def register_chain_in_golden(ip_names, name=None):
    """在 golden.py 中注册级联组合模型的函数"""
    chain_name = name or '_'.join(ip_names)
    snake = _snake(chain_name)
    func_calls = []
    for ip in ip_names:
        s = _snake(ip)
        func_calls.append(f"    r = m_{s}(r, writes, fi, st)")
    func_def = (f"def m_{snake}(fr, writes, fi, st):\n"
                f"    r = fr\n"
                + '\n'.join(func_calls) + '\n    return r')
    cfg = f"    '{snake}':        {{'frames': {max(3, len(ip_names))}, 'tol': 0, 'frac': 0.0}},"
    return func_def, cfg


# ─────────────────────────────────────────────────────────────────────────────
# 5. 主入口
# ─────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description='IP Spec 代码生成器')
    ap.add_argument('--spec', help='.ip_spec.yaml 文件路径')
    ap.add_argument('--name', help='IP 名称（与 --spec 二选一）')
    ap.add_argument('--chain', help='级联 IP 列表，逗号分隔，如 awb,gamma,sharpen')
    ap.add_argument('--register-chain', help='级联组合名，如 awb_gamma_sharpen')
    ap.add_argument('--dry-run', action='store_true', help='仅打印，不写文件')
    args = ap.parse_args()

    if args.chain:
        # 级联模式
        ip_names = [x.strip() for x in args.chain.split(',')]
        chain_name = args.register_chain or '_'.join(ip_names)
        print(f'🔗 生成级联组合: {chain_name} = {" → ".join(ip_names)}')

        if not args.dry_run:
            rtl_dir = os.path.join('rtl', chain_name)
            os.makedirs(rtl_dir, exist_ok=True)
            with open(os.path.join(rtl_dir, f'{chain_name}.v'), 'w') as f:
                f.write(generate_chain_rtl(ip_names, chain_name))
            print(f'  RTL      → rtl/{chain_name}/{chain_name}.v')
            with open(os.path.join(rtl_dir, 'regdef.json'), 'w') as f:
                f.write(generate_chain_regdef(ip_names, chain_name))
            print(f'  regdef   → rtl/{chain_name}/regdef.json')
            func_def, cfg = register_chain_in_golden(ip_names, chain_name)
            _inject_golden(chain_name, func_def, cfg)
            print(f'  golden   → scripts/golden.py (追加链式模型)')
            print(f'\n✅ 级联组合 "{chain_name}" 生成完成!')
            print(f'   运行验证: make verify IP={chain_name} WIDTH=64 HEIGHT=48')
        return

    spec_path = args.spec
    if not spec_path:
        print('错误: 请指定 --spec <文件> 或 --chain <ip列表>')
        sys.exit(1)

    if not os.path.exists(spec_path):
        print(f'错误: 文件不存在: {spec_path}')
        sys.exit(1)

    print(f'📦 加载规格: {spec_path}')
    spec = load_spec(spec_path)
    print(f'   IP 名称: {spec["name"]}')
    print(f'   算法类型: {spec.get("algorithm",{}).get("type","passthrough")}')
    print(f'   寄存器数: {len(spec.get("registers",[]))}')
    print()

    write_all(spec, dry_run=args.dry_run)


def _inject_golden(chain_name, func_def, cfg):
    """将链式模型注入 golden.py"""
    golden_path = 'scripts/golden.py'
    snake = _snake(chain_name)
    if os.path.exists(golden_path):
        with open(golden_path) as f:
            content = f.read()
    else:
        content = '#!/usr/bin/env python3\n"""golden.py""" import numpy as np\nMODELS = {}\nCONFIG = {}\n'

    # 替换或追加函数
    pat = rf'def m_{snake}\(fr, writes, fi, st\):.*?(?=\n\ndef |\nMODELS =|\Z)'
    if re.search(pat, content, re.DOTALL):
        content = re.sub(pat, func_def + '\n', content, flags=re.DOTALL)
    else:
        # 插在 MODELS 字典之前 (见 write_all 同处说明)
        content = content.replace(
            'MODELS = {', func_def + '\n\n\nMODELS = {', 1)

    # MODELS
    mod_str = f"    '{snake}': m_{snake},"
    if f"'{snake}':" not in content.split('MODELS')[1].split('CONFIG')[0]:
        content = content.replace('MODELS = {', f"MODELS = {{\n{mod_str}")

    # CONFIG
    cfg_pat = rf"CONFIG = \{{[^}}]*'{snake}'"
    if not re.search(cfg_pat, content):
        content = content.replace('CONFIG = {', f"CONFIG = {{\n{cfg}")

    with open(golden_path, 'w') as f:
        f.write(content)


if __name__ == '__main__':
    main()
