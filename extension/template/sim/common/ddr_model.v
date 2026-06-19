// ddr_model.v — 行为级 DDR4 仿真模型 (标准 AXI4 内存映射从接口)
//
// 真实 FPGA 中, DDR 控制器(MIG/Efinix DDR)向用户逻辑呈现的就是 AXI4 从接口;
// 本模型抽象掉 PHY/命令时序, 用一块行为内存 + AXI4 握手 + 可配置读写延迟,
// 复现 "带延迟的内存映射存储"。供帧缓冲等需要整帧随机访存的 IP 验证。
//
// 规格全参数化(按具体 IP 调整): 数据位宽 / 地址位宽 / 容量 / 读写延迟。
// 支持 INCR 突发, 读写各一笔在途(单 outstanding, 教学足够; 真实控制器可乱序多笔)。
// 简化: 忽略 awsize/arsize(按全宽 beat), 其它 burst 类型按 INCR 处理。
`timescale 1ns / 1ps

module ddr_model #(
    parameter C_DATA_WIDTH = 128,        // AXI 数据位宽 (DDR 总线宽)
    parameter C_ADDR_WIDTH = 32,         // AXI 地址位宽
    parameter C_ID_WIDTH   = 4,
    parameter C_MEM_WORDS  = 65536,      // 行为内存深度(字数), 按帧大小调整
    parameter C_RD_LATENCY = 12,         // 读延迟(周期), 模拟 DDR 访问延迟
    parameter C_WR_LATENCY = 6           // 写延迟(周期)
) (
    input  wire                      aclk,
    input  wire                      aresetn,
    // 写地址通道
    input  wire [C_ID_WIDTH-1:0]     s_axi_awid,
    input  wire [C_ADDR_WIDTH-1:0]   s_axi_awaddr,
    input  wire [7:0]                s_axi_awlen,
    input  wire [2:0]                s_axi_awsize,
    input  wire [1:0]                s_axi_awburst,
    input  wire                      s_axi_awvalid,
    output reg                       s_axi_awready,
    // 写数据通道
    input  wire [C_DATA_WIDTH-1:0]   s_axi_wdata,
    input  wire [C_DATA_WIDTH/8-1:0] s_axi_wstrb,
    input  wire                      s_axi_wlast,
    input  wire                      s_axi_wvalid,
    output reg                       s_axi_wready,
    // 写响应通道
    output reg  [C_ID_WIDTH-1:0]     s_axi_bid,
    output reg  [1:0]                s_axi_bresp,
    output reg                       s_axi_bvalid,
    input  wire                      s_axi_bready,
    // 读地址通道
    input  wire [C_ID_WIDTH-1:0]     s_axi_arid,
    input  wire [C_ADDR_WIDTH-1:0]   s_axi_araddr,
    input  wire [7:0]                s_axi_arlen,
    input  wire [2:0]                s_axi_arsize,
    input  wire [1:0]                s_axi_arburst,
    input  wire                      s_axi_arvalid,
    output reg                       s_axi_arready,
    // 读数据通道
    output reg  [C_ID_WIDTH-1:0]     s_axi_rid,
    output reg  [C_DATA_WIDTH-1:0]   s_axi_rdata,
    output reg  [1:0]                s_axi_rresp,
    output reg                       s_axi_rlast,
    output reg                       s_axi_rvalid,
    input  wire                      s_axi_rready
);

    localparam BYTES_PER_WORD = C_DATA_WIDTH / 8;
    // 字节地址 → 字索引: 右移 log2(BYTES_PER_WORD)
    function integer clog2; input integer v; integer i;
        begin clog2 = 0; for (i = v - 1; i > 0; i = i >> 1) clog2 = clog2 + 1; end
    endfunction
    localparam ADDR_LSB = clog2(BYTES_PER_WORD);

    reg [C_DATA_WIDTH-1:0] mem [0:C_MEM_WORDS-1];

    // ===================== 写路径 (单 outstanding) =====================
    localparam W_IDLE = 2'd0, W_DATA = 2'd1, W_RESP = 2'd2;
    reg [1:0]              wst;
    reg [C_ADDR_WIDTH-1:0] waddr;          // 字索引
    reg [C_ID_WIDTH-1:0]   wid;
    integer                wlat;

    always @(posedge aclk) begin
        if (!aresetn) begin
            wst <= W_IDLE; s_axi_awready <= 1'b0; s_axi_wready <= 1'b0;
            s_axi_bvalid <= 1'b0; s_axi_bresp <= 2'b00; s_axi_bid <= 0;
            waddr <= 0; wid <= 0; wlat <= 0;
        end else begin
            s_axi_awready <= 1'b0;
            case (wst)
                W_IDLE: begin
                    if (s_axi_awvalid) begin
                        s_axi_awready <= 1'b1;
                        waddr <= s_axi_awaddr >> ADDR_LSB;
                        wid   <= s_axi_awid;
                        s_axi_wready <= 1'b1;
                        wst   <= W_DATA;
                    end
                end
                W_DATA: begin
                    if (s_axi_wvalid && s_axi_wready) begin
                        if (waddr < C_MEM_WORDS) mem[waddr] <= s_axi_wdata;
                        waddr <= waddr + 1'b1;
                        if (s_axi_wlast) begin
                            s_axi_wready <= 1'b0;
                            wlat <= C_WR_LATENCY;
                            wst  <= W_RESP;
                        end
                    end
                end
                W_RESP: begin
                    if (wlat > 0) wlat <= wlat - 1;
                    else begin
                        s_axi_bvalid <= 1'b1;
                        s_axi_bresp  <= 2'b00;   // OKAY
                        s_axi_bid    <= wid;
                        if (s_axi_bvalid && s_axi_bready) begin
                            s_axi_bvalid <= 1'b0;
                            wst <= W_IDLE;
                        end
                    end
                end
            endcase
        end
    end

    // ===================== 读路径 (单 outstanding) =====================
    localparam R_IDLE = 2'd0, R_LAT = 2'd1, R_DATA = 2'd2;
    reg [1:0]              rst;
    reg [C_ADDR_WIDTH-1:0] raddr;          // 字索引
    reg [8:0]              rbeats;          // 剩余 beat 数
    reg [C_ID_WIDTH-1:0]   rid;
    integer                rlat;

    always @(posedge aclk) begin
        if (!aresetn) begin
            rst <= R_IDLE; s_axi_arready <= 1'b0;
            s_axi_rvalid <= 1'b0; s_axi_rlast <= 1'b0; s_axi_rresp <= 2'b00;
            s_axi_rdata <= 0; s_axi_rid <= 0;
            raddr <= 0; rbeats <= 0; rid <= 0; rlat <= 0;
        end else begin
            s_axi_arready <= 1'b0;
            case (rst)
                R_IDLE: begin
                    if (s_axi_arvalid) begin
                        s_axi_arready <= 1'b1;
                        raddr  <= s_axi_araddr >> ADDR_LSB;
                        rbeats <= s_axi_arlen + 1'b1;
                        rid    <= s_axi_arid;
                        rlat   <= C_RD_LATENCY;
                        rst    <= R_LAT;
                    end
                end
                R_LAT: begin
                    if (rlat > 0) rlat <= rlat - 1;
                    else begin
                        s_axi_rvalid <= 1'b1;
                        s_axi_rid    <= rid;
                        s_axi_rresp  <= 2'b00;
                        s_axi_rdata  <= (raddr < C_MEM_WORDS) ? mem[raddr]
                                        : {C_DATA_WIDTH{1'b0}};
                        s_axi_rlast  <= (rbeats == 9'd1);
                        rst <= R_DATA;
                    end
                end
                R_DATA: begin
                    if (s_axi_rvalid && s_axi_rready) begin
                        if (rbeats == 9'd1) begin   // 末 beat 已被接收
                            s_axi_rvalid <= 1'b0;
                            s_axi_rlast  <= 1'b0;
                            rst <= R_IDLE;
                        end else begin
                            raddr  <= raddr + 1'b1;
                            rbeats <= rbeats - 1'b1;
                            s_axi_rdata <= (raddr + 1 < C_MEM_WORDS)
                                           ? mem[raddr + 1] : {C_DATA_WIDTH{1'b0}};
                            s_axi_rlast <= (rbeats == 9'd2);
                        end
                    end
                end
            endcase
        end
    end

endmodule
