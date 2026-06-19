// passthrough.v — 直通 DUT, 用于验证仿真环境闭环
`timescale 1ns / 1ps

module passthrough #(
    parameter C_DATA_WIDTH = 32
) (
    input  wire                    aclk,
    input  wire                    aresetn,

    // AXI-Stream 输入
    input  wire                    s_axis_tvalid,
    output wire                    s_axis_tready,
    input  wire [C_DATA_WIDTH-1:0] s_axis_tdata,
    input  wire                    s_axis_tuser,
    input  wire                    s_axis_tlast,

    // AXI-Stream 输出
    output wire                    m_axis_tvalid,
    input  wire                    m_axis_tready,
    output wire [C_DATA_WIDTH-1:0] m_axis_tdata,
    output wire                    m_axis_tuser,
    output wire                    m_axis_tlast
);

assign m_axis_tvalid = s_axis_tvalid;
assign s_axis_tready = m_axis_tready;
assign m_axis_tdata  = s_axis_tdata;
assign m_axis_tuser  = s_axis_tuser;
assign m_axis_tlast  = s_axis_tlast;

endmodule
