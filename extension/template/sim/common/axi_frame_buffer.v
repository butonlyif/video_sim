// axi_frame_buffer.v — 帧缓冲封装 (AXI4 主, 接 ddr_model)
//
// 把 DDR 的随机访存包成两个简单的像素流端口, 供帧间处理 IP 使用:
//   写帧流 (wr_*)  : IP 把当前帧逐像素写入, 缓冲区存到 DDR 的"写槽"
//   读帧流 (rd_*)  : 缓冲区从 DDR 的"读槽"读出"上一帧", 逐像素给 IP
// 双槽 ping-pong: 每帧 SOF 交换读写槽, 实现"写当前帧 / 读上一帧"并行。
// prev_valid 在第二帧起为 1 (首帧无上一帧)。
//
// 简化(教学清晰): 1 像素 / beat (DDR 数据宽 = 像素宽), 单拍 AXI(awlen=0)。
// 真实设计可加突发(awlen)与位宽打包提升带宽, 此处从简。
`timescale 1ns / 1ps

module axi_frame_buffer #(
    parameter C_PIXEL_WIDTH  = 32,
    parameter C_ADDR_WIDTH   = 32,
    parameter C_ID_WIDTH     = 4,
    parameter C_FRAME_PIXELS = 3072,         // 每帧像素数 (W×H)
    parameter C_BASE_ADDR    = 32'h0000_0000
) (
    input  wire                      aclk,
    input  wire                      aresetn,
    // 写帧流 (存当前帧)
    input  wire [C_PIXEL_WIDTH-1:0]  wr_data,
    input  wire                      wr_valid,
    output wire                      wr_ready,
    input  wire                      wr_sof,      // 当前帧首像素=1
    // 读帧流 (取上一帧)
    output reg  [C_PIXEL_WIDTH-1:0]  rd_data,
    output reg                       rd_valid,
    input  wire                      rd_ready,
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

    // ===================== 写引擎 + 槽管理 =====================
    // 拥有 wr_slot/wptr/sof_cnt/prev_valid; 帧首先 WS_SWAP 交换再写, 消除特例。
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
    // SOF 像素目标槽 = 翻转后的写槽 (此拍 wr_slot 尚未更新), 偏移 0
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
                        // 新帧: 写首像素到翻转后写槽的 0 偏移, 同拍交换槽/清指针
                        m_axi_awaddr <= sof_base;
                        rd_slot <= wr_slot;        // 刚写满的槽变可读
                        wr_slot <= ~wr_slot;
                        wptr    <= 0;              // 本像素写 ptr0, WS_B 增到 1
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

    // ===================== 读引擎 (单拍 AR→R→OUT) =====================
    localparam RS_IDLE = 2'd0, RS_AR = 2'd1, RS_R = 2'd2, RS_OUT = 2'd3;
    reg [1:0] rst;
    reg [C_ADDR_WIDTH-1:0] rptr;
    wire [C_ADDR_WIDTH-1:0] rd_base = C_BASE_ADDR + (rd_slot ? SLOT_BYTES : 0);

    always @(posedge aclk) begin
        if (!aresetn) begin
            rst <= RS_IDLE; rptr <= 0; rd_valid <= 0; rd_data <= 0;
            m_axi_arvalid <= 0; m_axi_rready <= 0; m_axi_araddr <= 0;
            m_axi_arid <= 0;
        end else if (swap_pulse) begin
            // 新帧开始: 复位读指针, 从头读上一帧
            rst <= RS_IDLE; rptr <= 0; rd_valid <= 0;
            m_axi_arvalid <= 0; m_axi_rready <= 0;
        end else begin
            case (rst)
                RS_IDLE: if (prev_valid_r && rptr < C_FRAME_PIXELS) begin
                    m_axi_araddr  <= rd_base + rptr * BYTES;
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
                    rd_valid <= 1'b1;
                    rst <= RS_OUT;
                end
                RS_OUT: if (rd_ready) begin
                    rd_valid <= 1'b0;
                    rptr <= rptr + 1'b1;
                    rst  <= RS_IDLE;
                end
            endcase
        end
    end

endmodule
