// axi_frame_buffer_addr.v — 可插读地址的帧缓冲封装 (AXI4 主, 接 ddr_model)
//
// 平台改进 #5: axi_frame_buffer.v 只做线性 ping-pong(rptr++), 几何变换类 IP
// (转置/缩放/旋转)需要自定义读地址, 无法复用。本变体把"读指针"换成外部输入
// 的 rd_addr: IP 只负责产生读地址序列(转置=列优先, 缩放=步进, 旋转=仿射),
// AXI 时序与双槽 ping-pong 仍由本封装处理。
//
// 写帧流与 axi_frame_buffer 完全一致(逐像素写当前帧, SOF 交换槽)。
// 读侧改为请求/应答: IP 在 prev_valid 且 !rd_busy 时给出 rd_addr + rd_req,
// 封装发起 AR→R, 数据回来时 rd_valid 单拍脉冲伴随 rd_data。
//
// 容量自适配约定: 实例化 ddr_model 时用 localparam DDR_WORDS = 2 * C_FRAME_PIXELS
// (双槽), 避免按帧大小手算写死(本次 transpose 踩坑点)。
`timescale 1ns / 1ps

module axi_frame_buffer_addr #(
    parameter C_PIXEL_WIDTH  = 32,
    parameter C_ADDR_WIDTH   = 32,
    parameter C_ID_WIDTH     = 4,
    parameter C_FRAME_PIXELS = 3072,         // 每帧像素数 (W×H)
    parameter C_BASE_ADDR    = 32'h0000_0000
) (
    input  wire                      aclk,
    input  wire                      aresetn,
    // 写帧流 (存当前帧, 与 axi_frame_buffer 一致)
    input  wire [C_PIXEL_WIDTH-1:0]  wr_data,
    input  wire                      wr_valid,
    output wire                      wr_ready,
    input  wire                      wr_sof,      // 当前帧首像素=1
    // 读帧流 (按外部地址取上一帧)
    input  wire [C_ADDR_WIDTH-1:0]   rd_addr,     // 读像素索引(0..C_FRAME_PIXELS-1)
    input  wire                      rd_req,      // 请求读 rd_addr 处像素
    output wire                      rd_busy,     // 封装忙(上一笔未完成)
    output reg  [C_PIXEL_WIDTH-1:0]  rd_data,
    output reg                       rd_valid,    // rd_data 有效(单拍脉冲)
    output wire                      prev_valid,  // 存在上一帧
    // ---- AXI4 主接口 (接 ddr_model 从接口) ----
    output reg  [C_ID_WIDTH-1:0]     m_axi_awid,
    output reg  [C_ADDR_WIDTH-1:0]   m_axi_awaddr,
    output wire [7:0]                m_axi_awlen,
    output wire [2:0]                m_axi_awsize,
    output wire [1:0]                m_axi_awburst,
    output reg                       m_axi_awvalid,
    input  wire                      m_axi_awready,
    output reg  [C_PIXEL_WIDTH-1:0]  m_axi_wdata,
    output wire [C_PIXEL_WIDTH/8-1:0] m_axi_wstrb,
    output wire                      m_axi_wlast,
    output reg                       m_axi_wvalid,
    input  wire                      m_axi_wready,
    input  wire [C_ID_WIDTH-1:0]     m_axi_bid,
    input  wire [1:0]                m_axi_bresp,
    input  wire                      m_axi_bvalid,
    output reg                       m_axi_bready,
    output reg  [C_ID_WIDTH-1:0]     m_axi_arid,
    output reg  [C_ADDR_WIDTH-1:0]   m_axi_araddr,
    output wire [7:0]                m_axi_arlen,
    output wire [2:0]                m_axi_arsize,
    output wire [1:0]                m_axi_arburst,
    output reg                       m_axi_arvalid,
    input  wire                      m_axi_arready,
    input  wire [C_ID_WIDTH-1:0]     m_axi_rid,
    input  wire [C_PIXEL_WIDTH-1:0]  m_axi_rdata,
    input  wire [1:0]                m_axi_rresp,
    input  wire                      m_axi_rlast,
    input  wire                      m_axi_rvalid,
    output reg                       m_axi_rready
);
    localparam BYTES = C_PIXEL_WIDTH / 8;
    localparam SLOT_BYTES = C_FRAME_PIXELS * BYTES;

    // 突发恒定: 单拍 INCR, 全字节有效
    assign m_axi_awlen   = 8'd0;
    assign m_axi_arlen   = 8'd0;
    assign m_axi_awburst = 2'b01;
    assign m_axi_arburst = 2'b01;
    assign m_axi_awsize  = (BYTES == 8) ? 3'd3 : (BYTES == 4) ? 3'd2 : 3'd1;
    assign m_axi_arsize  = m_axi_awsize;
    assign m_axi_wstrb   = {(C_PIXEL_WIDTH/8){1'b1}};
    assign m_axi_wlast   = 1'b1;

    // ===================== 写引擎 + 槽管理 (同 axi_frame_buffer) =====================
    localparam WS_IDLE = 3'd0, WS_AW = 3'd2, WS_W = 3'd3, WS_B = 3'd4;
    reg [2:0] wst;
    reg       wr_slot, rd_slot;
    reg [1:0] sof_cnt;
    reg       prev_valid_r;
    reg [C_ADDR_WIDTH-1:0] wptr;
    reg [C_PIXEL_WIDTH-1:0] wpix;
    reg       swap_pulse;

    assign prev_valid = prev_valid_r;
    assign wr_ready   = (wst == WS_IDLE);

    wire [C_ADDR_WIDTH-1:0] wr_base = C_BASE_ADDR + (wr_slot ? SLOT_BYTES : 0);
    wire [C_ADDR_WIDTH-1:0] sof_base = C_BASE_ADDR + (~wr_slot ? SLOT_BYTES : 0);

    always @(posedge aclk) begin
        if (!aresetn) begin
            wst <= WS_IDLE; wr_slot <= 1'b0; rd_slot <= 1'b0;
            sof_cnt <= 2'd0; prev_valid_r <= 1'b0; wptr <= 0; wpix <= 0;
            swap_pulse <= 1'b0;
            m_axi_awvalid <= 0; m_axi_wvalid <= 0; m_axi_bready <= 0;
            m_axi_awaddr <= 0; m_axi_wdata <= 0; m_axi_awid <= 0;
        end else begin
            swap_pulse <= 1'b0;
            case (wst)
                WS_IDLE: if (wr_valid) begin
                    wpix <= wr_data;
                    m_axi_awvalid <= 1'b1;
                    wst <= WS_AW;
                    if (wr_sof) begin
                        m_axi_awaddr <= sof_base;
                        rd_slot <= wr_slot;
                        wr_slot <= ~wr_slot;
                        wptr    <= 0;
                        swap_pulse <= 1'b1;
                        if (sof_cnt < 2'd2) sof_cnt <= sof_cnt + 1'b1;
                        prev_valid_r <= (sof_cnt >= 2'd1);
                    end else begin
                        m_axi_awaddr <= wr_base + wptr * BYTES;
                    end
                end
                WS_AW: if (m_axi_awready) begin
                    m_axi_awvalid <= 1'b0;
                    m_axi_wdata   <= wpix;
                    m_axi_wvalid  <= 1'b1;
                    wst <= WS_W;
                end
                WS_W: if (m_axi_wready) begin
                    m_axi_wvalid <= 1'b0;
                    m_axi_bready <= 1'b1;
                    wst <= WS_B;
                end
                WS_B: if (m_axi_bvalid) begin
                    m_axi_bready <= 1'b0;
                    wptr <= wptr + 1'b1;
                    wst  <= WS_IDLE;
                end
            endcase
        end
    end

    // ===================== 读引擎 (外部地址驱动 AR→R) =====================
    // 与原版区别: 地址来自 rd_addr(外部), 由 rd_req 触发一笔, 不再自增 rptr。
    localparam RS_IDLE = 2'd0, RS_AR = 2'd1, RS_R = 2'd2;
    reg [1:0] rst;
    wire [C_ADDR_WIDTH-1:0] rd_base = C_BASE_ADDR + (rd_slot ? SLOT_BYTES : 0);

    assign rd_busy = (rst != RS_IDLE);

    always @(posedge aclk) begin
        if (!aresetn) begin
            rst <= RS_IDLE; rd_valid <= 0; rd_data <= 0;
            m_axi_arvalid <= 0; m_axi_rready <= 0; m_axi_araddr <= 0;
            m_axi_arid <= 0;
        end else if (swap_pulse) begin
            // 新帧开始: 中止在途读, 读槽已切换
            rst <= RS_IDLE; rd_valid <= 0;
            m_axi_arvalid <= 0; m_axi_rready <= 0;
        end else begin
            rd_valid <= 1'b0;            // 默认拉低, 仅 R 命中拍为 1
            case (rst)
                RS_IDLE: if (prev_valid_r && rd_req) begin
                    m_axi_araddr  <= rd_base + rd_addr * BYTES;
                    m_axi_arvalid <= 1'b1;
                    rst <= RS_AR;
                end
                RS_AR: if (m_axi_arready) begin
                    m_axi_arvalid <= 1'b0;
                    m_axi_rready  <= 1'b1;
                    rst <= RS_R;
                end
                RS_R: if (m_axi_rvalid) begin
                    m_axi_rready <= 1'b0;
                    rd_data  <= m_axi_rdata;
                    rd_valid <= 1'b1;       // 单拍脉冲
                    rst <= RS_IDLE;
                end
            endcase
        end
    end

endmodule
