# VIP Sim

awesom VIP 仿真验证环境。扩展内置完整的仿真工具包（Python 工具链 + AXI-Stream BFM + Makefile + 示例 DUT），通过"新建仿真项目"复制到用户自己的项目目录，所有开发与仿真都在用户项目内完成，扩展本身保持只读。

## 使用流程

1. **VIP Sim: 新建仿真项目** — 选择存放位置、输入项目名，扩展自动复制全部仿真文件并创建项目内 Python 环境（`.venv`），完成后打开新项目
2. 在项目的 `rtl/<你的IP>/` 写 RTL、`sim/tests/tb_<你的IP>.v` 写 Testbench、`rtl/<你的IP>/regdef.json` 写寄存器描述（均有 passthrough 示例可参考；用 Vibe Coding 时 AI 按 `.trae/rules/project_rules.md` 自动生成这三者）
3. **VIP Sim: 打开仿真控制台** — 图形界面完成全部操作：
   - 选择 IP、设置分辨率/帧数
   - **寄存器配置**（自动列出该 IP 全部寄存器，RW 可编辑、RO 展示缺省值，运行时写入 DUT）
   - **导入图像** / **生成图卡**（灰阶/彩条/灰卡/噪声/坏点注入等，复制进项目并设为激励源）
   - **运行仿真**（一键完成 激励生成 → iverilog 仿真 → 图像还原 → 质量分析）
   - **导出图像**（保存仿真输出到任意位置）
   - **结果分析**：图像对比（像素探针）/ 差异热力图 / 锐度 / 白平衡 / 直方图 / PSNR，每个维度独立弹出面板
   - **查看波形**（IDE 内打开 VCD，需 VaporView 等扩展）

## 全部命令

| 命令 | 说明 |
| --- | --- |
| VIP Sim: 新建仿真项目 | 复制工具包到新目录并建 venv |
| VIP Sim: 打开仿真控制台 | 主界面（运行/分析/寄存器/图卡） |
| VIP Sim: 查看波形 | IDE 内打开本次仿真 VCD |
| VIP Sim: 环境自检 | 检查 iverilog / venv / 环境文件版本 |
| VIP Sim: 同步环境文件到当前项目 | 扩展升级后更新老项目的 BFM/脚本/规则 |

项目内也可命令行操作：`make all`（完整流程）、`make regression`（全 IP 回归）、`make check`（直通自检）、`make sim WAVE=1`（带波形）。

## 环境要求

- iverilog / vvp（`brew install icarus-verilog`）
- python3（项目创建时自动建 venv 并安装 opencv/numpy/pillow，需联网）
- 波形查看（可选）：VaporView 扩展（`lramseyer.vaporview`）或 GTKWave（`brew install gtkwave`）

## 版本历史

| 版本   | 日期        | 主要变更                                           |
| ------ | ---------- | ------------------------------------------------- |
| v0.9.0 | 2026-06-14 | 控制台 GUI 美化：卡片式布局、渐变主按钮、Pill 标签、呼吸动画、双栏媒体面板、3 列分析网格、主题自适应 |
| v0.7.0 | 2026-06-14 | 视频仿真全链路：导入视频/流式多帧/逐帧预览/时序分析/MP4 导出 |
| v0.6.0 | 2026-06-13 | 金标准比对 (golden.py + compare.py + verify.py)；7 IP 参考模型 + 6 IP 逐位精确 |
| v0.5.0 | 2026-06-12 | 寄存器配置链路 (regdef.json → 控制台表单 → regcfg.hex → BFM)；预处理通道 (噪声/坏点/自定义 AI) |
| v0.4.0 | 2026-06-11 | 6 维度独立分析面板 + 图卡生成 (9 种内置图卡) |
| v0.3.0 | 2026-06-10 | 脚手架形态转向：扩展内置模板，新建项目复制 |
