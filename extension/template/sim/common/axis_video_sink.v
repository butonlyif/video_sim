// axis_video_sink.v — AXI-Stream 视频接收 BFM (C_PARALLEL=1)
// 接收到的每个像素立即 $fwrite 写入 result.hex。
// C_READY_MODE: 0 = tready 恒1; 1 = 随机反压 (C_READY_RATE% 概率就绪)。
`timescale 1ns / 1ps

module axis_video_sink #(
    parameter C_DATA_WIDTH  = 32,
    parameter C_WIDTH       = 64,
    parameter C_HEIGHT      = 48,
    parameter C_FRAMES      = 1,
    parameter C_READY_MODE  = 0,
    parameter C_READY_RATE  = 70,
    parameter C_RESULT_FILE = "result.hex"
) (
    input  wire                    aclk,
    input  wire                    aresetn,
    // AXI-Stream 输入
    input  wire                    s_axis_tvalid,
    output wire                    s_axis_tready,
    input  wire [C_DATA_WIDTH-1:0] s_axis_tdata,
    input  wire                    s_axis_tuser,
    input  wire                    s_axis_tlast,
    // 状态输出
    output reg                     frame_done,
    output reg  [31:0]             pixel_cnt
);

localparam TOTAL_PIXELS = C_WIDTH * C_HEIGHT * C_FRAMES;

integer fd;
reg     ready_r = 1'b1;

initial begin
    fd = $fopen(C_RESULT_FILE, "w");
    if (fd == 0) begin
        $display("ERROR: 无法打开结果文件 %s", C_RESULT_FILE);
        $finish;
    end
end

assign s_axis_tready = (C_READY_MODE == 0) ? 1'b1 : ready_r;

always @(posedge aclk) begin
    if (C_READY_MODE != 0)
        ready_r <= (($urandom % 100) < C_READY_RATE);
end

// 接收并写文件 + 协议检查
always @(posedge aclk) begin
    if (!aresetn) begin
        pixel_cnt  <= 32'd0;
        frame_done <= 1'b0;
    end else begin
        frame_done <= 1'b0;
        if (s_axis_tvalid && s_axis_tready) begin
            $fwrite(fd, "%08x\n", s_axis_tdata);

            // 协议检查: SOF 只应出现在帧首, EOL 只应出现在行尾
            if (s_axis_tuser !== (pixel_cnt % (C_WIDTH*C_HEIGHT) == 0))
                $display("ERROR: tuser 时序违规 at pixel %0d time %0t",
                         pixel_cnt, $time);
            if (s_axis_tlast !== (pixel_cnt % C_WIDTH == C_WIDTH-1))
                $display("ERROR: tlast 时序违规 at pixel %0d time %0t",
                         pixel_cnt, $time);

            pixel_cnt <= pixel_cnt + 1;
            if (pixel_cnt == TOTAL_PIXELS - 1) begin
                frame_done <= 1'b1;
                $fflush(fd);
            end
        end
    end
end

endmodule
