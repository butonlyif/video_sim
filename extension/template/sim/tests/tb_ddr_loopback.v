// tb_ddr_loopback.v — DDR + 帧缓冲 自检
// 连续写入 3 帧 (每帧像素 = 索引值), 验证读出的"上一帧"与上一帧写入一致。
// 证明 ddr_model + axi_frame_buffer 通路正确。
`timescale 1ns / 1ps

module tb_ddr_loopback;

parameter PIXELS = 256;          // 每帧像素 (小帧加快自检)
parameter FRAMES = 3;
localparam PW = 32;

reg aclk = 0;  always #4 aclk = ~aclk;
reg aresetn = 0;

// 帧缓冲 用户侧
reg  [PW-1:0] wr_data;  reg wr_valid, wr_sof;  wire wr_ready;
wire [PW-1:0] rd_data;  wire rd_valid;  reg rd_ready;  wire prev_valid;

// AXI 线网
wire [3:0] awid, bid, arid, rid;
wire [31:0] awaddr, araddr;  wire [7:0] awlen, arlen;
wire [2:0] awsize, arsize;  wire [1:0] awburst, arburst, bresp, rresp;
wire awvalid, awready, wvalid, wready, wlast, bvalid, bready;
wire arvalid, arready, rvalid, rready, rlast;
wire [PW-1:0] wdata, rdata;  wire [PW/8-1:0] wstrb;

axi_frame_buffer #(.C_PIXEL_WIDTH(PW), .C_FRAME_PIXELS(PIXELS)) u_fb (
    .aclk(aclk), .aresetn(aresetn),
    .wr_data(wr_data), .wr_valid(wr_valid), .wr_ready(wr_ready), .wr_sof(wr_sof),
    .rd_data(rd_data), .rd_valid(rd_valid), .rd_ready(rd_ready), .prev_valid(prev_valid),
    .m_axi_awid(awid), .m_axi_awaddr(awaddr), .m_axi_awlen(awlen), .m_axi_awsize(awsize),
    .m_axi_awburst(awburst), .m_axi_awvalid(awvalid), .m_axi_awready(awready),
    .m_axi_wdata(wdata), .m_axi_wstrb(wstrb), .m_axi_wlast(wlast),
    .m_axi_wvalid(wvalid), .m_axi_wready(wready),
    .m_axi_bid(bid), .m_axi_bresp(bresp), .m_axi_bvalid(bvalid), .m_axi_bready(bready),
    .m_axi_arid(arid), .m_axi_araddr(araddr), .m_axi_arlen(arlen), .m_axi_arsize(arsize),
    .m_axi_arburst(arburst), .m_axi_arvalid(arvalid), .m_axi_arready(arready),
    .m_axi_rid(rid), .m_axi_rdata(rdata), .m_axi_rresp(rresp), .m_axi_rlast(rlast),
    .m_axi_rvalid(rvalid), .m_axi_rready(rready));

ddr_model #(.C_DATA_WIDTH(PW), .C_MEM_WORDS(1024),
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

// 读侧: 每收到一个 rd 像素就校验 (期望 = 上一帧该位置的值)
// 第 f 帧写入值 = f*1000 + idx; 第 f 帧读出应为第 f-1 帧 = (f-1)*1000 + idx
integer rd_frame, rd_idx;
always @(posedge aclk) begin
    if (aresetn && rd_valid && rd_ready) begin
        rd_idx = rd_got % PIXELS;
        rd_frame = (rd_got / PIXELS) + 1;        // 读出帧号(从第2帧起)
        if (rd_data !== (rd_frame - 1) * 1000 + rd_idx) begin
            errors = errors + 1;
            if (errors <= 5)
                $display("ERROR: 读帧%0d idx%0d = %0d, 期望 %0d",
                         rd_frame, rd_idx, rd_data, (rd_frame - 1) * 1000 + rd_idx);
        end
        rd_got = rd_got + 1;
    end
end

integer f, i, rd_target;
initial begin
    wr_data = 0; wr_valid = 0; wr_sof = 0; rd_ready = 1; rd_target = 0;
    repeat (10) @(posedge aclk);
    aresetn = 1;
    @(posedge aclk);

    for (f = 0; f < FRAMES; f = f + 1) begin
        // 写一整帧 (标准握手: 呈现一拍被消费后立即撤 valid, 再等引擎空闲)
        for (i = 0; i < PIXELS; i = i + 1) begin
            wr_data = f * 1000 + i;
            wr_sof  = (i == 0);
            wr_valid = 1;
            @(posedge aclk);            // 引擎在 WS_IDLE 时本拍消费该像素
            #1 wr_valid = 0; wr_sof = 0; // #1 延迟撤销, 避免与时钟沿采样竞争
            while (!wr_ready) @(posedge aclk);   // 等引擎处理完返回空闲
        end
        // 写完第 f 帧后, 第 f-1 帧应在本帧窗口被读出; 等其读完再写下一帧,
        // 避免下一帧 SOF 提前交换槽中断未读完的读 (真实IP中读写本就1:1配速)
        if (f >= 1) begin
            rd_target = f * PIXELS;
            while (rd_got < rd_target) @(posedge aclk);
        end
    end
    repeat (200) @(posedge aclk);

    if (errors == 0 && rd_got == PIXELS * (FRAMES - 1))
        $display("PASS: DDR 帧缓冲自检通过, 读回 %0d 像素, 0 错误", rd_got);
    else
        $display("ERROR: 自检失败, 读回 %0d 像素(期望 %0d), %0d 错误",
                 rd_got, PIXELS * (FRAMES - 1), errors);
    $finish;
end

initial begin
    #(PIXELS * FRAMES * 200 * 8 + 200000);
    $display("ERROR: 仿真超时 (读回 %0d)", rd_got);
    $finish;
end

endmodule
