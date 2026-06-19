# VIP 仿真项目

本项目由 VIP Sim 扩展创建，包含完整的视频 IP 仿真验证环境。

## 快速开始（Vibe Coding 流程）

1. 阅读 `docs/IP开发课题说明书.md`，选定要开发的 IP 课题
2. 直接让 AI 生成代码，例如对 AI 说："实现课题二 Gamma 校正 IP，按项目规则放置文件"
   —— AI 会按 `.trae/rules/project_rules.md` 的约定，把 RTL 放到 `rtl/<ip名>/`、
   Testbench 放到 `sim/tests/tb_<ip名>.v`，并自动接入仿真环境
3. 命令面板运行 **VIP Sim: 打开仿真控制台**，IP 下拉框中会自动出现新 IP
4. 在控制台导入图像 → 编辑寄存器值 → 运行仿真 → 点击分析按钮查看结果
   （图像对比 / 差异热力图 / 锐度 / 白平衡 / 直方图 / PSNR / 金标准 PASS/FAIL）
5. （视频模式）导入视频 → 设置帧数 → 运行 → 逐帧预览/时序分析

也可以手写代码：参考 `rtl/passthrough/` 和 `sim/tests/tb_passthrough.v`。

## 目录结构

- `docs/` — IP 开发课题说明书（功能需求、接口标准、算法说明）
- `.trae/rules/` — AI 代码生成规则（Vibe Coding 约定）
- `rtl/` — 你的 IP RTL 代码
- `sim/common/` — AXI-Stream 视频源/接收 BFM（请勿修改）
- `sim/tests/` — 各 IP 的 Testbench
- `sim/testdata/` — 输入图像与激励/结果 hex
- `scripts/` — Python 工具链（图像↔hex、质量分析）
- `output/` — 仿真输出（图像/报告/波形）

## 命令行用法（可选）

```bash
make all IP=passthrough WIDTH=64 HEIGHT=48   # 完整流程
make check                                    # 直通自检
make sim WAVE=1                               # 带波形仿真
```
