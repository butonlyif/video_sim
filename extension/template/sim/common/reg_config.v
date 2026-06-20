// reg_config.v — 寄存器配置 BFM (写入 + 读回自检)
// 复位释放后分三步, 全部完成才放行视频流 (done):
//   ① 写阶段: 逐条把 regcfg.hex 的 (addr,data) 写入 DUT 配置接口;
//   ② 读回自检: 回读每个写过的寄存器, 与写入值逐位比对 → 打印 REGCHK PASS/FAIL;
//   ③ 完成: 拉高 done, 视频源 enable 接 done, 保证"配置+自检"先于视频流。
// 意义: 用逻辑实际跑一遍寄存器读/写时序, 证明 IP 的寄存器接口正确,
//       而非仅由表单把值写下去就算配置成功 (写了不等于读得回)。
// 文件格式: 每行一个 40bit hex 字 {addr[7:0], data[31:0]}, 全 F 行为结束哨兵。
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
    input  wire [31:0] cfg_rdata,   // DUT 回读数据 (组合读出, 随 cfg_addr)
    output reg         done
);

reg [39:0] mem [0:C_MAX_WRITES-1];

integer _i;
initial begin
    for (_i = 0; _i < C_MAX_WRITES; _i = _i + 1)
        mem[_i] = 40'hFF_FFFF_FFFF;
    $readmemh(C_CFG_FILE, mem);
end

localparam P_WRITE = 2'd0, P_READ = 2'd1, P_DONE = 2'd2;
reg [1:0]  phase;
reg [6:0]  idx;      // 写/读 共用索引
reg [6:0]  nwr;      // 实际写入条目数
reg        rstep;    // 读回两拍: 0=驱动地址, 1=采样比对
integer    errors;

always @(posedge aclk) begin
    if (!aresetn) begin
        phase     <= P_WRITE;
        idx       <= 7'd0;
        nwr       <= 7'd0;
        rstep     <= 1'b0;
        errors    <= 0;
        cfg_addr  <= 8'd0;
        cfg_wdata <= 32'd0;
        cfg_wen   <= 1'b0;
        cfg_ren   <= 1'b0;
        done      <= 1'b0;
    end else begin
        case (phase)
        // ── ① 写阶段 (逐条写入, 时序同原 BFM) ──
        P_WRITE: begin
            cfg_ren <= 1'b0;
            if (idx == C_MAX_WRITES[6:0] || mem[idx] == 40'hFF_FFFF_FFFF) begin
                cfg_wen <= 1'b0;
                nwr     <= idx;
                idx     <= 7'd0;
                rstep   <= 1'b0;
                phase   <= (idx == 7'd0) ? P_DONE : P_READ;  // 无写入则跳过自检
            end else begin
                cfg_addr  <= mem[idx][39:32];
                cfg_wdata <= mem[idx][31:0];
                cfg_wen   <= 1'b1;
                idx       <= idx + 7'd1;
            end
        end
        // ── ② 读回自检 (每个寄存器: 驱动地址 → 下一拍采样比对) ──
        P_READ: begin
            cfg_wen <= 1'b0;
            if (!rstep) begin
                cfg_addr <= mem[idx][39:32];
                cfg_ren  <= 1'b1;
                rstep    <= 1'b1;
            end else begin
                cfg_ren <= 1'b0;
                if (cfg_rdata !== mem[idx][31:0]) begin
                    errors <= errors + 1;
                    if (errors < 5)
                        $display("ERROR: 寄存器自检失配 @addr=0x%02h 写=0x%08h 读=0x%08h",
                                 mem[idx][39:32], mem[idx][31:0], cfg_rdata);
                end
                rstep <= 1'b0;
                if (idx == nwr - 7'd1) phase <= P_DONE;
                else                   idx   <= idx + 7'd1;
            end
        end
        // ── ③ 完成: 打印自检结论, 放行视频流 ──
        P_DONE: begin
            cfg_wen <= 1'b0;
            cfg_ren <= 1'b0;
            if (!done) begin
                if (nwr == 7'd0)
                    $display("REGCHK: 寄存器自检跳过 (无写入配置)");
                else if (errors == 0)
                    $display("REGCHK PASS: 寄存器读写自检通过 (%0d/%0d 读回一致)", nwr, nwr);
                else
                    $display("REGCHK FAIL: 寄存器读写自检 %0d/%0d 失配", errors, nwr);
            end
            done <= 1'b1;
        end
        endcase
    end
end

endmodule
