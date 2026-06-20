# Video Simulation - VIP Video Processing

## 项目描述
Video Simulation 是一个用于视频处理的仿真和测试框架，支持 VIP（Video Image Processing）算法的开发和验证。

## 主要功能
- 视频帧生成
- 图像质量分析（PSNR、锐度、白平衡等）
- 仿真测试框架
- 用户指南生成

## 技术栈
- Python (仿真脚本)
- Verilog (RTL 设计)
- Makefile (构建系统)

## 项目结构
```
video_sim/
├── CLAUDE.md                 # 项目说明
├── scripts/                  # 仿真脚本
│   ├── analyze.py           # 分析工具
│   ├── analyzers/           # 各种分析器
│   ├── gen_stimulus.py      # 激励生成
│   └── gen_output.py        # 输出生成
├── sim/                      # 仿真目录
│   ├── common/              # 公共模块
│   └── testdata/           # 测试数据
├── rtl/                      # RTL 设计
├── extension/               # VSCode 扩展
│   └── template/            # 项目模板
└── output/                  # 输出目录
```

## 开发注意事项
- 使用 scripts/ 目录下的工具进行视频仿真
- RTL 设计遵循 AXI Stream 视频接口标准
- 支持多种像素格式（RGB、YUV 等）
- 扩展功能提供 VSCode 集成

---

# CLAUDE.md Guidelines

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals and state a brief plan before implementation.
