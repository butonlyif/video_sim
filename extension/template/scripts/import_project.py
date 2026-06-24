#!/usr/bin/env python3
"""import_project.py — 把外部已有工程套进本仿真平台 (不污染原工程)

在仿真工作区根目录运行, 扫描 --src 指向的外部工程, 自动:
  1. 解析全部 .v/.sv 的 module 与端口;
  2. 识别 "IP 顶层" —— 同时具备 s_axis_* 输入与 m_axis_* 输出的模块;
  3. 沿实例化关系求每个 IP 的依赖闭包, 全局去重后复制 RTL 进工作区
     (IP 顶层 → rtl/<ip>/, 共享子模块 → rtl/_imported_common/, 每个唯一文件只拷一次,
      避免 sim.py 的 rtl/**/*.v 全局编译出现模块重定义);
  4. 按 DUT 真实端口名生成 sim/tests/tb_<ip>.v (容忍信号名变体、可选 tuser/tlast);
  5. 检测寄存器配置总线 (cfg_addr/cfg_wdata/cfg_wen) → 接 reg_config BFM + 生成 regdef.json 骨架。

用法:
  python scripts/import_project.py --src <外部工程目录> [--json]

--json: 仅向 stdout 打印机器可读的 JSON 摘要 (供扩展解析); 否则打印人类可读报告。
"""
import argparse
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Verilog 关键字 (实例化识别时排除, 避免把 if/case 等当模块名)
KEYWORDS = {
    'module', 'endmodule', 'input', 'output', 'inout', 'wire', 'reg', 'logic',
    'parameter', 'localparam', 'assign', 'always', 'begin', 'end', 'if', 'else',
    'case', 'endcase', 'for', 'while', 'generate', 'endgenerate', 'genvar',
    'initial', 'posedge', 'negedge', 'integer', 'function', 'endfunction',
    'task', 'endtask', 'signed', 'unsigned', 'default', 'casez', 'casex',
    'wait', 'repeat', 'forever', 'real', 'time', 'event', 'defparam',
}


# ---------- 预处理 ----------

def strip_comments(text):
    """去掉 // 行注释与 /* */ 块注释 (保留换行以便行号大致对应)。"""
    text = re.sub(r'/\*.*?\*/', lambda m: '\n' * m.group(0).count('\n'),
                  text, flags=re.S)
    text = re.sub(r'//[^\n]*', '', text)
    return text


# ---------- 解析 ----------

class Module:
    def __init__(self, name, file, ports, params, body):
        self.name = name
        self.file = file        # 绝对路径
        self.ports = ports      # [(dir, width_str, name)]
        self.params = params    # {name: default_str}
        self.body = body        # 模块体文本 (去注释), 供寄存器/实例化解析
        self.insts = set()      # 被例化的模块名集合 (resolve_insts 填)

    def port_names(self):
        return [p[2] for p in self.ports]

    def find_port(self, *patterns):
        """按正则(任一)匹配端口名, 返回首个 (dir,width,name) 或 None。"""
        for pat in patterns:
            rx = re.compile(pat, re.I)
            for p in self.ports:
                if rx.search(p[2]):
                    return p
        return None


def parse_params(param_block):
    """从 #( ... ) 文本解析 parameter 默认值。"""
    params = {}
    if not param_block:
        return params
    for m in re.finditer(r'parameter\s+(?:\w+\s+)?(\w+)\s*=\s*([^,)]+)',
                         param_block):
        params[m.group(1)] = m.group(2).strip()
    return params


def parse_ansi_ports(port_block):
    """解析 ANSI 风格端口表 (方向写在端口表内)。返回 [(dir,width,name)]。"""
    ports = []
    cur_dir = None
    cur_width = ''
    # 按逗号切分, 但方括号内的逗号不切 (端口宽度无逗号, 安全简单切)
    for raw in re.split(r',', port_block):
        seg = raw.strip()
        if not seg:
            continue
        m = re.match(
            r'(input|output|inout)?\s*(?:wire|reg|logic)?\s*(?:signed\s+)?'
            r'(\[[^\]]*\])?\s*(\w+)\s*$', seg)
        if not m:
            continue
        d, w, name = m.group(1), m.group(2), m.group(3)
        if d:
            cur_dir, cur_width = d, (w or '')
        ports.append((cur_dir or 'input', w or cur_width, name))
    return ports


def parse_nonansi_ports(port_block, body):
    """解析非 ANSI 端口 (端口表只有名字, 方向/宽度在模块体声明)。"""
    names = [n.strip() for n in re.split(r',', port_block)
             if n.strip() and re.match(r'^\w+$', n.strip())]
    decls = {}
    for m in re.finditer(
            r'\b(input|output|inout)\b\s*(?:wire|reg|logic)?\s*(?:signed\s+)?'
            r'(\[[^\]]*\])?\s*([\w\s,]+?);', body):
        d, w = m.group(1), m.group(2) or ''
        for nm in re.split(r',', m.group(3)):
            nm = nm.strip()
            if nm:
                decls[nm] = (d, w)
    ports = []
    for nm in names:
        d, w = decls.get(nm, ('input', ''))
        ports.append((d, w, nm))
    return ports


def parse_file(path, known_names_holder):
    """解析单个文件, 返回 {module_name: Module}。"""
    try:
        text = strip_comments(open(path, encoding='utf-8',
                                   errors='replace').read())
    except OSError:
        return {}
    mods = {}
    # 逐个 module ... endmodule
    for mm in re.finditer(r'\bmodule\s+(\w+)\s*'
                          r'(#\s*\((.*?)\))?\s*\((.*?)\)\s*;(.*?)\bendmodule',
                          text, flags=re.S):
        name = mm.group(1)
        param_block = mm.group(3) or ''
        port_block = mm.group(4) or ''
        body = mm.group(5) or ''
        if re.search(r'\b(input|output|inout)\b', port_block):
            ports = parse_ansi_ports(port_block)
        else:
            ports = parse_nonansi_ports(port_block, body)
        params = parse_params(param_block)
        mods[name] = Module(name, path, ports, params, body)
    return mods


def resolve_insts(mod, all_names):
    """在模块体里找被例化的已知模块名。"""
    body = mod.body
    found = set()
    for m in re.finditer(r'\b(\w+)\s*(?:#\s*\(.*?\))?\s*\w+\s*\(', body,
                         flags=re.S):
        nm = m.group(1)
        if nm in all_names and nm != mod.name and nm not in KEYWORDS:
            found.add(nm)
    mod.insts = found


# ---------- 宽度求值 ----------

def eval_width(width_str, params):
    """把 [MSB:0] 形式的位宽算成数据位数。失败返回 None。"""
    if not width_str:
        return 1
    inner = width_str.strip()[1:-1]          # 去 [ ]
    m = re.match(r'\s*(.+?)\s*:\s*(.+?)\s*$', inner)
    if not m:
        return None
    def ev(expr):
        e = expr.strip()
        for k, v in params.items():
            e = re.sub(r'\b' + re.escape(k) + r'\b', '(' + v + ')', e)
        # 反复展开嵌套参数 (至多几层)
        for _ in range(5):
            ne = e
            for k, v in params.items():
                ne = re.sub(r'\b' + re.escape(k) + r'\b', '(' + v + ')', ne)
            if ne == e:
                break
            e = ne
        if not re.match(r'^[\d\s+\-*/()]+$', e):
            return None
        try:
            return int(eval(e, {'__builtins__': {}}, {}))
        except Exception:
            return None
    hi, lo = ev(m.group(1)), ev(m.group(2))
    if hi is None or lo is None:
        return None
    return abs(hi - lo) + 1


# ---------- IP 识别 ----------

AXIS_IN = r's_?axis'        # 容忍 s_axis / saxis
AXIS_OUT = r'm_?axis'

def is_ip_top(mod):
    names = ' '.join(mod.port_names())
    has_in = re.search(AXIS_IN + r'.*?t(valid|data)', names, re.I)
    has_out = re.search(AXIS_OUT + r'.*?t(valid|data)', names, re.I)
    return bool(has_in and has_out)


def axis_map(mod, side):
    """返回该侧 (s/m) axis 信号实际端口名 (缺失为 None)。除 5 个基本信号外,
    还含可选 keep/strb/id/dest (TB 据此补接线, 避免 DUT 端口悬空)。"""
    pre = AXIS_IN if side == 's' else AXIS_OUT
    def f(sig):
        p = mod.find_port(pre + r'.*t' + sig + r'\b')
        return p[2] if p else None
    sigs = ('valid', 'ready', 'data', 'user', 'last', 'keep', 'strb', 'id', 'dest')
    return {sig: f(sig) for sig in sigs}


def port_width(mod, name):
    """端口位宽(整数), 解析失败返回 None。"""
    if not name:
        return None
    p = next((x for x in mod.ports if x[2] == name), None)
    return eval_width(p[1], mod.params) if p else None


def width_to_format(bits):
    """tdata 位宽 → 像素格式 (与 pixfmt.from_width 一致, 此处内联以免依赖 numpy)。"""
    if bits == 8:
        return 'RAW8'
    if bits in (10, 12, 16):
        return 'RAW16'
    if bits == 24:
        return 'RGB24'
    return 'RGB888'        # 32 或未知


def detect_bayer(mod):
    """从 RTL 识别 Bayer 排列 (注释/标识符里的 RGGB/GRBG/BGGR/GBRG), 缺省 RGGB。"""
    try:
        raw = open(mod.file, encoding='utf-8', errors='replace').read().upper()
    except OSError:
        raw = ''
    for pat in ('RGGB', 'GRBG', 'BGGR', 'GBRG'):
        if pat in raw:
            return 'BAYER_' + pat
    return 'BAYER_RGGB'


def _verilog_int(tok):
    """解析 Verilog 数字字面量: 32'h0002_0000 / 8'd30 / 30 → int。"""
    tok = tok.strip().replace('_', '')
    m = re.match(r"\d*'([hdbHDB])([0-9A-Fa-f]+)", tok)
    if m:
        base = {'h': 16, 'd': 10, 'b': 2}[m.group(1).lower()]
        try:
            return int(m.group(2), base)
        except ValueError:
            return 0
    try:
        return int(tok)
    except ValueError:
        return 0


def parse_registers(mod):
    """从 RTL 解析真实寄存器映射 (best-effort): localparam REG_* 给地址+名+说明,
    写 case(出现 cfg_wdata) 判 RW, 读 case 字面量/复位赋值给默认值。解析不出返回 None。
    不确定的默认值回退 0, 由用户在 regdef.json 校正 (清单可改)。"""
    raw = open(mod.file, encoding='utf-8', errors='replace').read()
    # localparam REG_NAME = W'hHH;  + 可选行尾 // 说明
    reg_rx = re.compile(
        r"localparam\s+(REG_\w+)\s*=\s*\d*'[hH]([0-9A-Fa-f_]+)\s*;[ \t]*(?://[ \t]*(.*))?")
    found = [(m.group(1), int(m.group(2).replace('_', ''), 16),
              (m.group(3) or '').strip()) for m in reg_rx.finditer(raw)]
    if not found:
        return None
    body = strip_comments(raw)
    # 写 case 标签(含 cfg_wdata)= RW; 区分单语句与 begin..end 块
    write_syms = set()
    for m in re.finditer(r'(REG_\w+)\s*:\s*begin(.*?)end', body, re.S):
        if 'cfg_wdata' in m.group(2):
            write_syms.add(m.group(1))
    for m in re.finditer(r'(REG_\w+)\s*:\s*(\w+)\s*<=\s*cfg_wdata', body):
        write_syms.add(m.group(1))
    # 写 case 中 "REG_X: sig <= cfg_wdata" → 内部信号 (用于查复位默认)
    wr_sig = dict(re.findall(r'(REG_\w+)\s*:\s*(?:begin\s*)?(\w+)\s*<=\s*cfg_wdata', body))
    reset_val = dict(re.findall(
        r"(\w+)\s*<=\s*(\d+'[hHdDbB][0-9A-Fa-f_]+)\s*;", body))
    # 读 case 字面量 (RO 默认, 如 VERSION)
    read_lit = dict(re.findall(
        r"(REG_\w+)\s*:\s*cfg_rdata\s*=\s*(\d+'[hHdD][0-9A-Fa-f_]+)", body))

    regs = []
    for sym, addr, desc in sorted(found, key=lambda x: x[1]):
        rw = sym in write_syms
        default = 0
        if not rw and sym in read_lit:
            default = _verilog_int(read_lit[sym])
        elif rw and sym in wr_sig and wr_sig[sym] in reset_val:
            default = _verilog_int(reset_val[wr_sig[sym]])
        regs.append({
            'addr': '0x%02x' % addr,
            'name': sym[4:] if sym.startswith('REG_') else sym,
            'access': 'RW' if rw else 'RO',
            'default': '0x%08x' % (default & 0xFFFFFFFF),
            'desc': desc,
        })
    return regs


def cfg_map(mod):
    """检测寄存器配置总线, 返回端口名 dict 或 None。"""
    addr = mod.find_port(r'cfg_?addr', r'reg_?addr')
    wdata = mod.find_port(r'cfg_?wdata', r'reg_?wdata', r'cfg_?din')
    wen = mod.find_port(r'cfg_?wen', r'reg_?wen', r'cfg_?we\b')
    if not (addr and wdata and wen):
        return None
    ren = mod.find_port(r'cfg_?ren', r'cfg_?re\b')
    rdata = mod.find_port(r'cfg_?rdata', r'cfg_?dout')
    return {
        'addr': addr[2], 'wdata': wdata[2], 'wen': wen[2],
        'ren': ren[2] if ren else None,
        'rdata': rdata[2] if rdata else None,
    }


def clk_rst(mod):
    clk = mod.find_port(r'^a?clk', r'clock')
    rst = mod.find_port(r'a?resetn', r'rst_?n', r'^a?rst', r'reset')
    rst_active_low = bool(rst and re.search(r'(n|_n)$|resetn', rst[2], re.I))
    return (clk[2] if clk else 'aclk',
            rst[2] if rst else 'aresetn',
            rst_active_low)


# ---------- TB 生成 ----------

def conn(port_name, signal):
    """生成一行端口连接, port_name 为 None 时跳过 (返回 '')。"""
    if not port_name:
        return ''
    return f'    .{port_name:<16}({signal}),\n'


def gen_tb(ip, mod, in_width, out_width, smap, mmap, cfg, clk, rst, rst_low):
    """生成 tb_<ip>.v 文本。结构对齐 tb_passthrough, 保证 sim.py 的 -P 注参生效。
    in_width/out_width: DUT 输入/输出 tdata 位宽 (source/sink 各按之, 不强行统一)。"""
    rst_deassert = '1\'b1' if rst_low else '1\'b0'

    # DUT 端口连接
    dut = ''
    dut += conn(clk, 'aclk')
    dut += conn(rst, 'aresetn' if rst_low else '~aresetn')
    dut += conn(smap['valid'], 'src_tvalid')
    dut += conn(smap['ready'], 'src_tready')
    dut += conn(smap['data'], 'src_tdata')
    dut += conn(smap['user'], 'src_tuser')
    dut += conn(smap['last'], 'src_tlast')
    # 可选输入信号: keep/strb 接全 1 (字节全有效), id/dest 接 0, 避免 DUT 端口悬空
    for sig, allone in (('keep', True), ('strb', True), ('id', False), ('dest', False)):
        pn = smap[sig]
        if pn:
            w = port_width(mod, pn) or 1
            dut += conn(pn, ("{%d{1'b1}}" % w) if allone else ("%d'd0" % w))
    dut += conn(mmap['valid'], 'dut_tvalid')
    dut += conn(mmap['ready'], 'dut_tready')
    dut += conn(mmap['data'], 'dut_tdata')
    dut += conn(mmap['user'], 'dut_tuser')
    dut += conn(mmap['last'], 'dut_tlast')
    # DUT 的可选输出信号悬空即可 (sink 不需要), 不接
    if cfg:
        dut += conn(cfg['addr'], 'cfg_addr')
        dut += conn(cfg['wdata'], 'cfg_wdata')
        dut += conn(cfg['wen'], 'cfg_wen')
        dut += conn(cfg['ren'], 'cfg_ren')
        dut += conn(cfg['rdata'], 'cfg_rdata')
    dut = dut.rstrip(',\n')   # 去掉末尾逗号

    # sink 侧: DUT 缺 tuser/tlast 时, 用 TB 计数器按像素序号重建 SOF/EOL,
    # 与 sink 的校验式 (pixel_cnt%(W*H)==0 / pixel_cnt%W==W-1) 完全对齐。
    need_framing = not (mmap['user'] and mmap['last'])
    framing = ''
    if need_framing:
        framing = '''
// DUT 未携带 tuser/tlast: 按输出像素序号重建帧/行边界供 sink 校验
reg [31:0] obeat = 0;
always @(posedge aclk)
    if (!aresetn) obeat <= 0;
    else if (dut_tvalid && dut_tready) obeat <= obeat + 1;
wire syn_tuser = (obeat % (C_WIDTH * C_HEIGHT) == 0);
wire syn_tlast = (obeat % C_WIDTH == C_WIDTH - 1);
'''
    sink_tuser = 'dut_tuser' if mmap['user'] else 'syn_tuser'
    sink_tlast = 'dut_tlast' if mmap['last'] else 'syn_tlast'

    # DUT 输入侧无 tready: 无反压, source 自由推流 (否则 src_tready 悬空)
    if not smap['ready']:
        framing += '\nassign src_tready = 1\'b1;  // DUT 无 s_axis_tready, 无反压\n'

    enable_sig = 'cfg_done' if cfg else '1\'b1'

    cfg_decl = cfg_inst = ''
    if cfg:
        rdata_wire = 'wire [31:0] cfg_rdata;\n' if cfg['rdata'] else ''
        rdata_tie = '' if cfg['rdata'] else \
            '    .cfg_rdata    (32\'d0),    // DUT 无回读口, 自检将报 FAIL (仅提示)\n'
        cfg_decl = (
            'wire [7:0]  cfg_addr;\n'
            'wire [31:0] cfg_wdata;\n'
            'wire        cfg_wen, cfg_ren, cfg_done;\n' + rdata_wire)
        cfg_inst = f'''
reg_config #(
    .C_CFG_FILE("sim/testdata/regcfg.hex")
) u_regcfg (
    .aclk     (aclk),
    .aresetn  (aresetn),
    .cfg_addr (cfg_addr),
    .cfg_wdata(cfg_wdata),
    .cfg_wen  (cfg_wen),
    .cfg_ren  (cfg_ren),
{rdata_tie}    {".cfg_rdata(cfg_rdata)," if cfg['rdata'] else ""}
    .done     (cfg_done)
);
'''

    return f'''// tb_{ip}.v — 自动生成 (import_project.py): source -> {mod.name} -> sink
`timescale 1ns / 1ps

module tb_{ip};

parameter C_WIDTH  = 64;
parameter C_HEIGHT = 48;
parameter C_FRAMES = 1;
parameter C_STREAM = 0;
parameter C_STIMULUS_FILE = "sim/testdata/stimulus.hex";
parameter C_RESULT_FILE   = "sim/testdata/result.hex";
parameter C_READY_MODE    = 0;

// 输入/输出 tdata 位宽各按 DUT 真实端口 (RAW8/RGB24/RGB888 等可不同, 如 demosaic)
localparam C_IN_WIDTH  = {in_width};
localparam C_OUT_WIDTH = {out_width};

reg aclk    = 1'b0;
reg aresetn = 1'b0;

always #4 aclk = ~aclk;   // 125 MHz

// source -> dut (输入位宽)
wire                   src_tvalid, src_tready, src_tuser, src_tlast;
wire [C_IN_WIDTH-1:0]  src_tdata;
// dut -> sink (输出位宽)
wire                   dut_tvalid, dut_tready, dut_tuser, dut_tlast;
wire [C_OUT_WIDTH-1:0] dut_tdata;

wire        src_done, sink_done;
wire [31:0] src_cnt, sink_cnt;
{cfg_decl}
axis_video_source #(
    .C_DATA_WIDTH   (C_IN_WIDTH),
    .C_WIDTH        (C_WIDTH),
    .C_HEIGHT       (C_HEIGHT),
    .C_FRAMES       (C_FRAMES), .C_STREAM(C_STREAM),
    .C_FLUSH        (2 * C_WIDTH),   // 冲刷流水线 IP 的帧尾 (行缓冲/3x3 必需)
    .C_STIMULUS_FILE(C_STIMULUS_FILE)
) u_source (
    .aclk         (aclk),
    .aresetn      (aresetn),
    .enable       ({enable_sig}),
    .m_axis_tvalid(src_tvalid),
    .m_axis_tready(src_tready),
    .m_axis_tdata (src_tdata),
    .m_axis_tuser (src_tuser),
    .m_axis_tlast (src_tlast),
    .frame_done   (src_done),
    .pixel_cnt    (src_cnt)
);

{mod.name} u_dut (
{dut}
);
{cfg_inst}{framing}
axis_video_sink #(
    .C_DATA_WIDTH (C_OUT_WIDTH),
    .C_WIDTH      (C_WIDTH),
    .C_HEIGHT     (C_HEIGHT),
    .C_FRAMES     (C_FRAMES),
    .C_READY_MODE (C_READY_MODE),
    .C_RESULT_FILE(C_RESULT_FILE)
) u_sink (
    .aclk         (aclk),
    .aresetn      (aresetn),
    .s_axis_tvalid(dut_tvalid),
    .s_axis_tready(dut_tready),
    .s_axis_tdata (dut_tdata),
    .s_axis_tuser ({sink_tuser}),
    .s_axis_tlast ({sink_tlast}),
    .frame_done   (sink_done),
    .pixel_cnt    (sink_cnt)
);

initial begin
    if ($test$plusargs("WAVE")) begin
        $dumpfile("output/waves/{ip}.vcd");
        $dumpvars(0, tb_{ip});
    end
end

initial begin
    repeat (10) @(posedge aclk);
    aresetn = {rst_deassert};
    wait (sink_done);
    repeat (10) @(posedge aclk);
    $display("PASS: 仿真完成, 共接收 %0d 像素 (%0dx%0d x %0d帧)",
             sink_cnt, C_WIDTH, C_HEIGHT, C_FRAMES);
    $finish;
end

initial begin
    #(C_WIDTH * C_HEIGHT * C_FRAMES * 8 * 100 + 100_000);
    $display("ERROR: 仿真超时");
    $finish;
end

endmodule
'''


# 标准视频 IP 寄存器映射 (平台约定): 检测到 cfg 总线即按此填全 regdef,
# 使 reg_config 的写入+读回自检 (REGCHK) 覆盖真实寄存器。WIDTH/HEIGHT 的
# default 由仿真分辨率在 gen_default_regcfg / 控制台运行时按名覆盖。
REGDEF_STANDARD = {
    "_comment": "自动生成: 标准视频 IP 寄存器映射。WIDTH/HEIGHT 运行时按仿真分辨率覆盖。"
                " 若与实际 RTL 不符请按真实寄存器调整。",
    "registers": [
        {"addr": "0x00", "name": "VERSION", "access": "RO",
         "default": "0x00010000", "desc": "IP 版本号 (只读)"},
        {"addr": "0x04", "name": "CTRL", "access": "RW",
         "default": "0x00000001", "desc": "bit0=enable bit1=bypass"},
        {"addr": "0x10", "name": "WIDTH", "access": "RW",
         "default": "0x00000040", "desc": "图像宽度 (运行时按仿真分辨率覆盖)"},
        {"addr": "0x14", "name": "HEIGHT", "access": "RW",
         "default": "0x00000030", "desc": "图像高度 (运行时按仿真分辨率覆盖)"},
        {"addr": "0x18", "name": "FORMAT", "access": "RW",
         "default": "0x00000000", "desc": "像素格式 (0=RGB888)"},
        {"addr": "0x1c", "name": "PARAM0", "access": "RW",
         "default": "0x00000000", "desc": "通用参数 0"}
    ]
}


# ---------- 主流程 ----------

def find_sources(src):
    files = []
    for dirpath, _, names in os.walk(src):
        for n in names:
            if n.endswith(('.v', '.sv')):
                files.append(os.path.join(dirpath, n))
    return files


def file_closure(top_name, modules):
    """求 top 的依赖闭包涉及的文件集合 (含 top 自身文件)。"""
    seen, files = set(), set()
    stack = [top_name]
    while stack:
        nm = stack.pop()
        if nm in seen or nm not in modules:
            continue
        seen.add(nm)
        files.add(modules[nm].file)
        stack.extend(modules[nm].insts)
    return files


def collect_readmem_paths(rtl_root):
    """扫描已拷入的 RTL, 收集 $readmemh/$readmemb 引用的文件路径 (RTL 自带数据,
    如 gamma LUT / 系数表)。这些路径相对仿真 cwd(工作区根), 需一并拷入。

    支持两种写法: 字符串字面量 `$readmemh("path", ...)`, 以及参数 `$readmemh(NAME,...)`
    + `parameter NAME = "path"` (gamma_lut 即用后者)。"""
    rx_lit = re.compile(r'\$readmem[hb]\s*\(\s*"([^"]+)"')
    rx_arg = re.compile(r'\$readmem[hb]\s*\(\s*([A-Za-z_]\w*)\s*,')
    rx_par = re.compile(r'(?:parameter|localparam)\s+(?:\w+\s+)?'
                        r'(\w+)\s*=\s*"([^"]+)"')
    paths = set()
    for dp, _, names in os.walk(rtl_root):
        for n in names:
            if not n.endswith(('.v', '.sv')):
                continue
            try:
                txt = strip_comments(open(os.path.join(dp, n),
                                          encoding='utf-8', errors='replace').read())
            except OSError:
                continue
            paths.update(rx_lit.findall(txt))
            params = dict(rx_par.findall(txt))      # 参数名 → 字符串值
            for name in rx_arg.findall(txt):
                if name in params:
                    paths.add(params[name])
    return paths


def find_data_file(src, rel):
    """在源工程定位 $readmemh 引用的数据文件: 先按工程根相对路径, 再按路径结尾/文件名。"""
    direct = os.path.join(src, rel)
    if os.path.isfile(direct):
        return direct
    norm = rel.replace('\\', '/').lstrip('./')
    base = os.path.basename(norm)
    fallback = None
    for dp, _, names in os.walk(src):
        for n in names:
            full = os.path.join(dp, n)
            if full.replace('\\', '/').endswith('/' + norm):
                return full
            if n == base and fallback is None:
                fallback = full
    return fallback


def unique_dest(dest_dir, basename, used):
    """避免 basename 冲突。"""
    name = basename
    i = 1
    while os.path.join(dest_dir, name) in used or \
            (name in {os.path.basename(u) for u in used}):
        stem, ext = os.path.splitext(basename)
        name = f'{stem}_{i}{ext}'
        i += 1
    return name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True, help='外部工程目录')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    src = os.path.abspath(args.src)
    if not os.path.isdir(src):
        print(json.dumps({'error': f'目录不存在: {src}'}) if args.json
              else f'错误: 目录不存在 {src}')
        sys.exit(1)

    # 1. 解析全部文件
    modules = {}
    for f in find_sources(src):
        for nm, mod in parse_file(f, None).items():
            if nm not in modules:        # 同名模块保留首个
                modules[nm] = mod
    all_names = set(modules)
    for mod in modules.values():
        resolve_insts(mod, all_names)

    # 2. 识别 IP 顶层 = 有 axis 主从对 且 不被其它模块例化 (真正的根)
    instantiated = set()
    for mod in modules.values():
        instantiated |= mod.insts
    axis_mods = [m for m in modules.values() if is_ip_top(m)]
    ip_tops = [m for m in axis_mods if m.name not in instantiated]
    # 若所有 axis 模块都互相例化(异常), 退化为全部 axis 模块
    if not ip_tops and axis_mods:
        ip_tops = axis_mods

    if not ip_tops:
        msg = {'ips': [], 'skipped': [], 'note': '未发现含 s_axis+m_axis 的 IP 顶层'}
        print(json.dumps(msg, ensure_ascii=False) if args.json
              else '未在该工程发现 AXI-Stream 视频 IP (需同时含 s_axis_* 与 m_axis_*)')
        sys.exit(0 if args.json else 2)

    # 3. 全局去重的文件分配: 顶层文件 → rtl/<ip>/; 其余依赖 → _imported_common/
    top_files = {m.file for m in ip_tops}
    ip_dir_root = os.path.join(ROOT, 'rtl')
    common_dir = os.path.join(ip_dir_root, '_imported_common')

    report_ips = []
    common_needed = set()

    for mod in ip_tops:
        ip = re.sub(r'[^A-Za-z0-9_]', '_', mod.name)
        mmap = axis_map(mod, 'm')
        smap = axis_map(mod, 's')
        # 输入/输出 tdata 位宽各自检测 (可不同, 如 demosaic RAW8→RGB24)
        in_width = port_width(mod, smap['data']) or 32
        out_width = port_width(mod, mmap['data']) or 32
        in_format = width_to_format(in_width)
        out_format = width_to_format(out_width)
        # 单通道 RAW 输入 + RGB 输出 = 去马赛克: 输入按真实 Bayer 马赛克激励
        if in_width <= 16 and out_width >= 24:
            in_format = detect_bayer(mod)
        cfg = cfg_map(mod)
        clk, rst, rst_low = clk_rst(mod)

        # 拷贝顶层文件
        ip_dir = os.path.join(ip_dir_root, ip)
        os.makedirs(ip_dir, exist_ok=True)
        shutil.copy2(mod.file, os.path.join(ip_dir, os.path.basename(mod.file)))

        # 依赖文件(除顶层们)归入 common
        for f in file_closure(mod.name, modules):
            if f not in top_files:
                common_needed.add(f)

        # 生成 TB: source 按输入位宽, sink 按输出位宽
        tb = gen_tb(ip, mod, in_width, out_width, smap, mmap, cfg,
                    clk, rst, rst_low)
        with open(os.path.join(ROOT, 'sim', 'tests', f'tb_{ip}.v'), 'w') as fh:
            fh.write(tb)

        # 每 IP 清单 ip.json: 输入/输出格式 (激励/还原据此自适应)
        if in_format != 'RGB888' or out_format != 'RGB888':
            with open(os.path.join(ip_dir, 'ip.json'), 'w') as fh:
                json.dump({'in_format': in_format, 'out_format': out_format},
                          fh, ensure_ascii=False, indent=2)

        # 寄存器: 优先从 RTL 解析真实映射, 解析不出再退标准映射
        regs = parse_registers(mod) if cfg else None
        if cfg:
            spec = ({'_comment': '从 RTL 自动解析 (best-effort)。默认值/说明可能不全, '
                                 '请按实际 RTL 校正。', 'registers': regs}
                    if regs else REGDEF_STANDARD)
            with open(os.path.join(ip_dir, 'regdef.json'), 'w') as fh:
                json.dump(spec, fh, ensure_ascii=False, indent=2)

        report_ips.append({
            'ip': ip, 'module': mod.name,
            'in_width': in_width, 'out_width': out_width,
            'in_format': in_format, 'out_format': out_format,
            'has_cfg': bool(cfg),
            'regs_parsed': len(regs) if regs else 0,
            'top_file': os.path.relpath(mod.file, src),
            'ports': {'s': smap, 'm': mmap},
            'warnings': _warnings(mod, smap, mmap, cfg, in_width, out_width),
        })

    # 4. 复制共享子模块 (全局去重)
    if common_needed:
        os.makedirs(common_dir, exist_ok=True)
    used = set()
    for f in sorted(common_needed):
        name = unique_dest(common_dir, os.path.basename(f), used)
        dest = os.path.join(common_dir, name)
        shutil.copy2(f, dest)
        used.add(dest)

    # 5. 复制 RTL 自带数据文件 ($readmemh/$readmemb 引用, 如 gamma LUT),
    #    按 RTL 期望的相对路径(相对仿真 cwd=工作区根)拷入。
    data_copied, data_missing = [], []
    for rel in sorted(collect_readmem_paths(ip_dir_root)):
        if os.path.isabs(rel):
            data_missing.append(f'{rel} (绝对路径, 未处理)')
            continue
        dest = os.path.join(ROOT, rel)
        if os.path.isfile(dest):
            continue                       # 工作区已有(如模板自带), 不覆盖
        found = find_data_file(src, rel)
        if found:
            os.makedirs(os.path.dirname(dest) or '.', exist_ok=True)
            shutil.copy2(found, dest)
            data_copied.append(rel)
        else:
            data_missing.append(rel)

    result = {
        'src': src,
        'ips': report_ips,
        'common_files': sorted(os.path.basename(f) for f in common_needed),
        'data_files': data_copied,
        'missing_data': data_missing,
        'all_modules': len(modules),
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        _print_human(result)


def _warnings(mod, smap, mmap, cfg, in_width, out_width):
    w = []
    if not smap['ready']:
        w.append('输入侧无 tready (无反压握手, source 将持续推流)')
    if not mmap['user'] and not mmap['last']:
        w.append('输出侧无 tuser/tlast (帧/行边界由像素计数推断)')
    if cfg and not cfg['rdata']:
        w.append('寄存器无回读口 cfg_rdata, 读回自检会报 FAIL (功能不受影响)')
    if in_width <= 16 and out_width >= 24:
        w.append(f'去马赛克 IP: 输入按真实 Bayer 马赛克激励 ({detect_bayer(mod)}), '
                 f'输出还原为 {width_to_format(out_width)}')
    elif in_width != out_width:
        w.append(f'输入位宽 {in_width} ≠ 输出位宽 {out_width} (跨格式 IP, '
                 f'激励/还原已分别按 {width_to_format(in_width)}/'
                 f'{width_to_format(out_width)})')
    elif in_width == 8:
        w.append('输入为 8 位单通道 (RAW/灰度): 激励用图像亮度')
    return w


def _print_human(r):
    print(f'\n源工程: {r["src"]}')
    print(f'解析模块数: {r["all_modules"]}  |  识别 IP: {len(r["ips"])}  |  '
          f'共享子模块: {len(r["common_files"])}\n')
    for ip in r['ips']:
        fmt = (ip["in_format"] if ip["in_format"] == ip["out_format"]
               else f'{ip["in_format"]}→{ip["out_format"]}')
        reg = f', {ip["regs_parsed"]}寄存器' if ip["has_cfg"] else ''
        print(f'● {ip["ip"]}  (module {ip["module"]}, {fmt}{reg})')
        print(f'    顶层: {ip["top_file"]}')
        for w in ip['warnings']:
            print(f'    ⚠ {w}')
    if r['common_files']:
        print(f'\n共享子模块 → rtl/_imported_common/: '
              f'{", ".join(r["common_files"])}')
    if r.get('data_files'):
        print(f'\nRTL 数据文件 ($readmemh): {", ".join(r["data_files"])}')
    if r.get('missing_data'):
        print(f'\n⚠ 未找到的 RTL 数据文件(请手动放入工作区对应路径): '
              f'{", ".join(r["missing_data"])}')
    print('\n完成。在控制台选择对应 IP 即可运行仿真。')


if __name__ == '__main__':
    main()
