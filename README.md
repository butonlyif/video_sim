# VIP 仿真验证平台

端到端视频 IP 仿真验证环境：给一张图进去，经过你的 RTL 模块，拿到一张图出来，最后告诉你处理得好不好。

## 核心能力

- **图像/视频 → 仿真激励**：自动将真实图像转换为 Verilog `$readmemh` 可读的 hex 激励
- **一键仿真**：iverilog 编译 + 运行 + 结果采集全自动
- **金标准比对**：Python 参考模型按位复现 RTL 定点运算，自动判定 PASS/FAIL
- **多维度质量分析**：锐度、白平衡、PSNR、直方图、Gamma 曲线
- **Trae / VS Code 扩展**：图形化控制台，无需命令行

## 快速开始

### 1. 安装

#### 前提条件

| 组件 | macOS | Windows | Linux |
|------|-------|---------|-------|
| iverilog | `brew install icarus-verilog` | `scoop install icarus-verilog` | `sudo apt install iverilog` |
| Python 3.10+ | 系统自带或 `brew install python@3.10` | [python.org](https://python.org) 下载安装 | 系统自带 |
| GTKWave（可选） | `brew install gtkwave` | `scoop install gtkwave` | `sudo apt install gtkwave` |
| VaporView（可选） | VS Code 扩展市场搜索 `lramseyer.vaporview` 安装 | 同左 | 同左 |

> Python 图像依赖（opencv/numpy/pillow）无需手动安装，新建项目时自动创建 `.venv` 并安装。

#### 安装扩展

**方式 A：命令行安装**

```bash
code --install-extension release/v1.0.1/vip-sim-1.0.1.vsix
```

**方式 B：IDE 内安装**

打开 Trae / VS Code → 扩展面板 → `···` → `Install from VSIX` → 选择 `release/v1.0.1/vip-sim-1.0.1.vsix`

安装完成后**重新加载窗口**：`Ctrl+Shift+P` (Windows) / `Cmd+Shift+P` (Mac) → `Developer: Reload Window`

### 2. 新建仿真项目

控制台中点击「新建仿真项目」，扩展自动复制工具包并创建 Python 虚拟环境。

### 3. 开发 IP

```bash
# 方式一：Spec 驱动（推荐，RTL + 金标准同时生成）
python scripts/gen_ip_spec.py --spec specs/my_filter.yaml

# 方式二：AI 生成（Vibe Coding）
# 在 Trae 中描述需求，AI 按 .trae/rules/project_rules.md 自动生成
```

### 4. 运行仿真

```bash
# 命令行
python scripts/sim.py all IP=passthrough WIDTH=64 HEIGHT=48

# 或在控制台点击「运行仿真」
```

## 项目结构

```
video_sim/
├── extension/           # Trae / VS Code 扩展（产品本体）
│   ├── extension.js     # 扩展入口
│   ├── package.json     # 扩展清单
│   ├── template/        # 仿真环境模板（打进 vsix，用户新建项目时复制）
│   │   ├── rtl/         # 示例 IP (passthrough)
│   │   ├── sim/         # AXI-Stream BFM + Testbench
│   │   ├── scripts/     # Python 工具链（仿真/分析/金标准）
│   │   └── Makefile     # 薄封装（转发给 sim.py）
├── docs/                # 技术文档
│   ├── DESIGN_SPEC.md   # 仿真系统设计说明书
│   ├── EXTENSION_DESIGN.md  # 扩展设计说明书
│   └── USER_GUIDE.md    # 用户使用说明书
├── release/             # 交付物归档（按版本）
└── scripts/             # 开发用辅助脚本
```

## 跨平台支持

| 平台 | 仿真器 | 构建 | 状态 |
|------|--------|------|------|
| macOS | `brew install icarus-verilog` | `make` 或 `python scripts/sim.py` | 完整支持 |
| Linux | `apt install iverilog` | `make` 或 `python scripts/sim.py` | 完整支持 |
| Windows | `scoop install icarus-verilog` | `python scripts/sim.py`（无需 make） | 完整支持 |

## 文档

| 文档 | 说明 |
|------|------|
| [用户使用说明书](docs/USER_GUIDE.md) | 安装、控制台操作、7 个典型场景、6 项分析详解、FAQ |
| [设计说明书](docs/DESIGN_SPEC.md) | 系统架构、Python 工具链、Verilog BFM、文件格式规范 |
| [扩展设计说明书](docs/EXTENSION_DESIGN.md) | IDE 扩展架构、功能模块、技术决策 |
| [发布说明](release/v1.0.1/RELEASE_NOTES.md) | 最新版本变更清单 |

## 版本

**当前版本：v1.0.1** | [安装包](release/v1.0.1/vip-sim-1.0.1.vsix)

详见 [版本历史](extension/README.md#版本历史)。
