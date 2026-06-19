// reg_config.v — 寄存器配置 BFM
// 从 regcfg.hex 读取写序列, 复位释放后逐条写入 DUT 配置接口, 完成后拉高 done。
// 文件格式: 每行一个 40bit hex 字 {addr[7:0], data[31:0]}, 全 F 行为结束哨兵。
// 用法: 视频源 BFM 的 enable 接 done, 保证配置先于视频流生效。
`timescale 1ns / 1ps

module reg_config #(
    parameter C_CFG_FILE   = "sim/testdata/regcfg.hex",
    parameter C_MAX_WRITES = 64
) (
    input  wire        aclk,
    input  wire        aresetn,
    output reg  [7:0]  cfg_addr,
    output reg  [31:0] cfg_wdata,
    output reg         cfg_wen,
    output reg         cfg_ren,
    output reg         done
);

reg [39:0] mem [0:C_MAX_WRITES-1];

integer _i;
initial begin
    for (_i = 0; _i < C_MAX_WRITES; _i = _i + 1)
        mem[_i] = 40'hFF_FFFF_FFFF;
    $readmemh(C_CFG_FILE, mem);
end

reg [6:0] idx;

always @(posedge aclk) begin
    if (!aresetn) begin
        idx       <= 7'd0;
        cfg_addr  <= 8'd0;
        cfg_wdata <= 32'd0;
        cfg_wen   <= 1'b0;
        cfg_ren   <= 1'b0;
        done      <= 1'b0;
    end else if (!done) begin
        if (idx == C_MAX_WRITES[6:0] || mem[idx] == 40'hFF_FFFF_FFFF) begin
            cfg_wen <= 1'b0;
            done    <= 1'b1;
        end else begin
            cfg_addr  <= mem[idx][39:32];
            cfg_wdata <= mem[idx][31:0];
            cfg_wen   <= 1'b1;
            idx       <= idx + 7'd1;
        end
    end else begin
        cfg_wen <= 1'b0;
    end
end

endmodule
