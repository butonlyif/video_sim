# VIP Sim

awesom VIP 仿真验证环境。扩展内置完整的仿真工具包（Python 工具链 + AXI-Stream BFM + Makefile + 示例 DUT），通过"新建仿真项目"复制到用户自己的项目目录，所有开发与仿真都在用户项目内完成，扩展本身保持只读。

两种起步方式：**新建仿真项目**（从零搭脚手架，自己写 IP）或 **导入已有工程**（把一个已有 RTL 工程套进平台，自动识别其中的多个 AXI-Stream 视频 IP 并生成 Testbench，不改动原工程）。

## 使用流程

### A. 导入已有工程（已有 RTL，想看代码效果）

**VIP Sim: 导入已有工程并仿真** — 选择目标工程目录，扩展会：

1. 在工程旁创建独立仿真工作区 `<工程名>_vipsim`（**不污染原工程**），复制工具链并建 `.venv`
2. 扫描全部 `.v/.sv`，识别"IP 顶层"——顶层端口同时含 `s_axis_*` 与 `m_axis_*` 的模块
3. 沿实例化关系求依赖闭包，全局去重后复制 RTL（IP 顶层 → `rtl/<ip>/`，共享子模块 → `rtl/_imported_common/`）
4. 按 DUT 真实端口名自动生成 `sim/tests/tb_<ip>.v`（容忍信号名变体、可选 `tready`/`tuser`/`tlast`；检测寄存器配置总线 `cfg_*` → 接 `reg_config` BFM 并生成 `regdef.json` 骨架）
5. 打开工作区，控制台中即可逐个选择识别出的 IP 运行仿真

> 缺 `tuser`/`tlast` 的 IP，TB 会按像素序号自动重建帧/行边界；缺 `s_axis_tready` 的 IP，source 自由推流（无反压）。原 RTL 修改后重新执行本命令即可刷新工作区。

### B. 新建仿真项目（从零开始写 IP）

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
| VIP Sim: 导入已有工程并仿真 | 扫描外部工程、识别多个 AXI-Stream IP、在工程旁建独立工作区并生成 TB |
| VIP Sim: 打开仿真控制台 | 主界面（运行/分析/寄存器/图卡） |
| VIP Sim: 查看波形 | IDE 内打开本次仿真 VCD |
| VIP Sim: 环境自检 | 检查 iverilog / venv / 环境文件版本 |
| VIP Sim: 同步环境文件到当前项目 | 扩展升级后更新老项目的 BFM/脚本/规则 |

项目内也可命令行操作（纯 Python，Win/Mac/Linux 通用，**无需 make**）：`python scripts/sim.py all`（完整流程）、`... regression`（全 IP 回归）、`... check`（直通自检）、`... sim WAVE=1`（带波形）。Mac/Linux 亦可用等价 `make` 封装。

## 环境要求

- iverilog / vvp（Mac: `brew install icarus-verilog`；Windows: `scoop install icarus-verilog`）
- python3（项目创建时自动建 venv 并安装 opencv/numpy/pillow，需联网）
- 构建编排为纯 Python，**Windows 无需安装 GNU Make**
- 波形查看（可选）：VaporView 扩展（`lramseyer.vaporview`）或 GTKWave（`brew install gtkwave`）

## 版本历史

| 版本   | 日期        | 主要变更                                           |
| ------ | ---------- | ------------------------------------------------- |
| v0.9.8 | 2026-06-24 | 新增"导入已有工程"：扫描外部 RTL 工程，自动识别多个 AXI-Stream 视频 IP，在工程旁建独立工作区（不污染原工程），**贴着目标 IP 生成仿真代码**——按真实输入/输出位宽自适应像素格式（RAW8/RGB24/RGB888，支持 demosaic 跨格式）、从 RTL 解析真实寄存器映射（地址/RW-RO/默认值/说明）、补 tkeep/tstrb 接线与复位极性、拷贝 `$readmemh` 数据文件（含参数路径）、流水线 IP 帧尾自动冲刷；缺 tuser/tlast 重建帧边界、缺 tready 自由推流。实测某真实工程 13 个 IP 全端到端 PASS |
| v0.9.7 | 2026-06-21 | 真正的 Windows 兼容：纯 Python 构建编排 `scripts/sim.py` 取代 make，消除 GNU Make 依赖与 Unix shell builtins（mkdir -p/rm -f/glob/diff/管道）；Makefile 退化为薄封装；环境自检改为不用 Unix 管道 |
| v0.9.0 | 2026-06-14 | 控制台 GUI 美化：卡片式布局、渐变主按钮、Pill 标签、呼吸动画、双栏媒体面板、3 列分析网格、主题自适应 |
| v0.7.0 | 2026-06-14 | 视频仿真全链路：导入视频/流式多帧/逐帧预览/时序分析/MP4 导出 |
| v0.6.0 | 2026-06-13 | 金标准比对 (golden.py + compare.py + verify.py)；7 IP 参考模型 + 6 IP 逐位精确 |
| v0.5.0 | 2026-06-12 | 寄存器配置链路 (regdef.json → 控制台表单 → regcfg.hex → BFM)；预处理通道 (噪声/坏点/自定义 AI) |
| v0.4.0 | 2026-06-11 | 6 维度独立分析面板 + 图卡生成 (9 种内置图卡) |
| v0.3.0 | 2026-06-10 | 脚手架形态转向：扩展内置模板，新建项目复制 |
