// tb_passthrough.v — 闭环验证 Testbench: source → passthrough → sink
`timescale 1ns / 1ps

module tb_passthrough;

parameter C_WIDTH  = 64;
parameter C_HEIGHT = 48;
parameter C_FRAMES = 1;
parameter C_STREAM = 0;
parameter C_STIMULUS_FILE = "sim/testdata/stimulus.hex";
parameter C_RESULT_FILE   = "sim/testdata/result.hex";
parameter C_READY_MODE    = 0;

localparam C_DATA_WIDTH = 32;

reg aclk    = 1'b0;
reg aresetn = 1'b0;

always #4 aclk = ~aclk;   // 125 MHz

// source → dut
wire        src_tvalid, src_tready, src_tuser, src_tlast;
wire [31:0] src_tdata;
// dut → sink
wire        dut_tvalid, dut_tready, dut_tuser, dut_tlast;
wire [31:0] dut_tdata;

wire        src_done, sink_done;
wire [31:0] src_cnt, sink_cnt;

axis_video_source #(
    .C_DATA_WIDTH   (C_DATA_WIDTH),
    .C_WIDTH        (C_WIDTH),
    .C_HEIGHT       (C_HEIGHT),
    .C_FRAMES       (C_FRAMES), .C_STREAM(C_STREAM),
    .C_STIMULUS_FILE(C_STIMULUS_FILE)
) u_source (
    .aclk         (aclk),
    .aresetn      (aresetn),
    .enable       (1'b1),
    .m_axis_tvalid(src_tvalid),
    .m_axis_tready(src_tready),
    .m_axis_tdata (src_tdata),
    .m_axis_tuser (src_tuser),
    .m_axis_tlast (src_tlast),
    .frame_done   (src_done),
    .pixel_cnt    (src_cnt)
);

passthrough #(
    .C_DATA_WIDTH(C_DATA_WIDTH)
) u_dut (
    .aclk         (aclk),
    .aresetn      (aresetn),
    .s_axis_tvalid(src_tvalid),
    .s_axis_tready(src_tready),
    .s_axis_tdata (src_tdata),
    .s_axis_tuser (src_tuser),
    .s_axis_tlast (src_tlast),
    .m_axis_tvalid(dut_tvalid),
    .m_axis_tready(dut_tready),
    .m_axis_tdata (dut_tdata),
    .m_axis_tuser (dut_tuser),
    .m_axis_tlast (dut_tlast)
);

axis_video_sink #(
    .C_DATA_WIDTH (C_DATA_WIDTH),
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
    .s_axis_tuser (dut_tuser),
    .s_axis_tlast (dut_tlast),
    .frame_done   (sink_done),
    .pixel_cnt    (sink_cnt)
);

// 波形 dump: +WAVE 时开启
initial begin
    if ($test$plusargs("WAVE")) begin
        $dumpfile("output/waves/passthrough.vcd");
        $dumpvars(0, tb_passthrough);
    end
end

// 主流程
initial begin
    repeat (10) @(posedge aclk);
    aresetn = 1'b1;

    wait (sink_done);
    repeat (10) @(posedge aclk);

    $display("PASS: 仿真完成, 共接收 %0d 像素 (%0dx%0d x %0d帧)",
             sink_cnt, C_WIDTH, C_HEIGHT, C_FRAMES);
    $finish;
end

// 超时保护
initial begin
    #(C_WIDTH * C_HEIGHT * C_FRAMES * 8 * 100 + 100_000);
    $display("ERROR: 仿真超时");
    $finish;
end

endmodule
