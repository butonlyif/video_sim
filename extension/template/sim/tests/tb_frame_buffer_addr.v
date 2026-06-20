// tb_frame_buffer_addr.v — 可插读地址帧缓冲 自检 (平台改进 #5)
// 写 2 帧后, 用"转置"读地址序列(列优先)从上一帧随机访存读回, 验证每个
// 读回像素 == 其被请求的源地址值。证明 axi_frame_buffer_addr 的自定义寻址
// 通路正确, 且 ddr 容量按 2 槽自适配(DDR_WORDS = 2 * PIXELS)。
`timescale 1ns / 1ps

module tb_frame_buffer_addr;

parameter W = 8;
parameter H = 8;
localparam PIXELS = W * H;
localparam PW = 32;
localparam DDR_WORDS = 2 * PIXELS;     // 容量自适配: 双槽 ping-pong

reg aclk = 0;  always #4 aclk = ~aclk;
reg aresetn = 0;

// 帧缓冲 用户侧
reg  [PW-1:0] wr_data;  reg wr_valid, wr_sof;  wire wr_ready;
reg  [31:0]   rd_addr;  reg rd_req;  wire rd_busy;
wire [PW-1:0] rd_data;  wire rd_valid;  wire prev_valid;

// AXI 线网
wire [3:0] awid, bid, arid, rid;
wire [31:0] awaddr, araddr;  wire [7:0] awlen, arlen;
wire [2:0] awsize, arsize;  wire [1:0] awburst, arburst, bresp, rresp;
wire awvalid, awready, wvalid, wready, wlast, bvalid, bready;
wire arvalid, arready, rvalid, rready, rlast;
wire [PW-1:0] wdata, rdata;  wire [PW/8-1:0] wstrb;

axi_frame_buffer_addr #(.C_PIXEL_WIDTH(PW), .C_FRAME_PIXELS(PIXELS)) u_fb (
    .aclk(aclk), .aresetn(aresetn),
    .wr_data(wr_data), .wr_valid(wr_valid), .wr_ready(wr_ready), .wr_sof(wr_sof),
    .rd_addr(rd_addr), .rd_req(rd_req), .rd_busy(rd_busy),
    .rd_data(rd_data), .rd_valid(rd_valid), .prev_valid(prev_valid),
    .m_axi_awid(awid), .m_axi_awaddr(awaddr), .m_axi_awlen(awlen), .m_axi_awsize(awsize),
    .m_axi_awburst(awburst), .m_axi_awvalid(awvalid), .m_axi_awready(awready),
    .m_axi_wdata(wdata), .m_axi_wstrb(wstrb), .m_axi_wlast(wlast),
    .m_axi_wvalid(wvalid), .m_axi_wready(wready),
    .m_axi_bid(bid), .m_axi_bresp(bresp), .m_axi_bvalid(bvalid), .m_axi_bready(bready),
    .m_axi_arid(arid), .m_axi_araddr(araddr), .m_axi_arlen(arlen), .m_axi_arsize(arsize),
    .m_axi_arburst(arburst), .m_axi_arvalid(arvalid), .m_axi_arready(arready),
    .m_axi_rid(rid), .m_axi_rdata(rdata), .m_axi_rresp(rresp), .m_axi_rlast(rlast),
    .m_axi_rvalid(rvalid), .m_axi_rready(rready));

ddr_model #(.C_DATA_WIDTH(PW), .C_MEM_WORDS(DDR_WORDS),
            .C_RD_LATENCY(8), .C_WR_LATENCY(4)) u_ddr (
    .aclk(aclk), .aresetn(aresetn),
    .s_axi_awid(awid), .s_axi_awaddr(awaddr), .s_axi_awlen(awlen), .s_axi_awsize(awsize),
    .s_axi_awburst(awburst), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
    .s_axi_wdata(wdata), .s_axi_wstrb(wstrb), .s_axi_wlast(wlast),
    .s_axi_wvalid(wvalid), .s_axi_wready(wready),
    .s_axi_bid(bid), .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
    .s_axi_arid(arid), .s_axi_araddr(araddr), .s_axi_arlen(arlen), .s_axi_arsize(arsize),
    .s_axi_arburst(arburst), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
    .s_axi_rid(rid), .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rlast(rlast),
    .s_axi_rvalid(rvalid), .s_axi_rready(rready));

integer errors = 0;
integer rd_got = 0;

// 写一整帧 (像素值 = base + 行优先索引)
task write_frame(input [31:0] base);
    integer i;
    begin
        for (i = 0; i < PIXELS; i = i + 1) begin
            wr_data = base + i;
            wr_sof  = (i == 0);
            wr_valid = 1;
            @(posedge aclk);
            #1 wr_valid = 0; wr_sof = 0;
            while (!wr_ready) @(posedge aclk);
        end
    end
endtask

integer k, tx, ty, src;
initial begin
    wr_data = 0; wr_valid = 0; wr_sof = 0; rd_addr = 0; rd_req = 0;
    repeat (10) @(posedge aclk);
    aresetn = 1;
    @(posedge aclk);

    write_frame(32'd0);          // 帧0: 像素值 = 行优先索引
    write_frame(32'h1000);       // 帧1: 触发交换, prev=帧0, rd_slot 稳定

    while (!prev_valid) @(posedge aclk);

    // 转置读: 列优先遍历 (tx,ty) → 源地址 = ty*W+tx, 期望读回该地址值
    for (k = 0; k < PIXELS; k = k + 1) begin
        tx = k / H;
        ty = k % H;
        src = ty * W + tx;
        while (rd_busy) @(posedge aclk);
        rd_addr = src;
        rd_req  = 1;
        @(posedge aclk);
        #1 rd_req = 0;
        while (rd_valid !== 1'b1) @(posedge aclk);
        if (rd_data !== src) begin
            errors = errors + 1;
            if (errors <= 5)
                $display("ERROR: 读地址 %0d = %0d, 期望 %0d", src, rd_data, src);
        end
        rd_got = rd_got + 1;
        @(posedge aclk);
    end

    if (errors == 0 && rd_got == PIXELS)
        $display("PASS: 可插寻址帧缓冲自检通过, 转置读回 %0d 像素, 0 错误", rd_got);
    else
        $display("ERROR: 自检失败, 读回 %0d 像素(期望 %0d), %0d 错误",
                 rd_got, PIXELS, errors);
    $finish;
end

initial begin
    #(PIXELS * 400 * 8 + 200000);
    $display("ERROR: 仿真超时 (读回 %0d)", rd_got);
    $finish;
end

endmodule
