// axis_video_source.v — AXI-Stream 视频源 BFM (C_PARALLEL=1)
// 从 stimulus.hex 读入像素, 按 ready/valid 握手逐像素输出。
// tuser = 帧首像素 (SOF), tlast = 行尾像素 (EOL)。
`timescale 1ns / 1ps

module axis_video_source #(
    parameter C_DATA_WIDTH    = 32,
    parameter C_WIDTH         = 64,
    parameter C_HEIGHT        = 48,
    parameter C_FRAMES        = 1,
    parameter C_STREAM        = 0,   // 0=单帧replay C_FRAMES次; 1=流式读N个不同帧(视频)
    parameter C_FLUSH         = 0,   // 帧后追加的冲刷像素数: 让有流水线延迟的 IP(行缓冲/3x3)
                                     // 把卡在管线里的帧尾像素推出 (data=0, tuser=0, 保持行 tlast)
    parameter C_STIMULUS_FILE = "stimulus.hex"
) (
    input  wire                    aclk,
    input  wire                    aresetn,
    input  wire                    enable,   // 流启动门控 (接 reg_config.done, 无配置时接 1'b1)
    // AXI-Stream 输出
    output wire                    m_axis_tvalid,
    input  wire                    m_axis_tready,
    output wire [C_DATA_WIDTH-1:0] m_axis_tdata,
    output wire                    m_axis_tuser,
    output wire                    m_axis_tlast,
    // 状态输出
    output reg                     frame_done,
    output reg  [31:0]             pixel_cnt
);

localparam PIXELS_PER_FRAME = C_WIDTH * C_HEIGHT;
localparam TOTAL_PIXELS     = PIXELS_PER_FRAME * C_FRAMES;
// 流式模式 mem 需容纳所有帧; replay 模式仅一帧
localparam MEM_DEPTH = C_STREAM ? TOTAL_PIXELS : PIXELS_PER_FRAME;

reg [C_DATA_WIDTH-1:0] mem [0:MEM_DEPTH-1];

initial begin
    $readmemh(C_STIMULUS_FILE, mem);
end

// 当前帧内像素索引 (SOF/EOL 标记用); 数据索引: 流式=全局序号, replay=帧内序号
wire [31:0] frame_idx = pixel_cnt % PIXELS_PER_FRAME;
wire [31:0] data_idx  = C_STREAM ? pixel_cnt : frame_idx;
wire        in_frame  = (pixel_cnt < TOTAL_PIXELS);          // 真实帧数据阶段
wire        sending   = (pixel_cnt < TOTAL_PIXELS + C_FLUSH); // 含冲刷阶段
wire [31:0] rd_idx    = in_frame ? data_idx : 32'd0;         // 冲刷阶段不越界读 mem

assign m_axis_tvalid = aresetn && enable && sending;
assign m_axis_tdata  = in_frame ? mem[rd_idx] : {C_DATA_WIDTH{1'b0}};
assign m_axis_tuser  = in_frame && (frame_idx == 0);
assign m_axis_tlast  = (frame_idx % C_WIDTH == C_WIDTH - 1);

always @(posedge aclk) begin
    if (!aresetn) begin
        pixel_cnt  <= 32'd0;
        frame_done <= 1'b0;
    end else begin
        frame_done <= 1'b0;
        if (m_axis_tvalid && m_axis_tready) begin
            pixel_cnt <= pixel_cnt + 1;
            if (pixel_cnt == TOTAL_PIXELS - 1)
                frame_done <= 1'b1;
        end
    end
end

endmodule
