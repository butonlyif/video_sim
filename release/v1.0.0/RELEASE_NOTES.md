# VIP Sim v1.0.0 — 发布说明

发布日期：2026-06-24

## 交付内容

| 文件 | 说明 |
|---|---|
| `vip-sim-1.0.0.vsix` | 扩展安装包（54 文件，134KB），内置完整仿真工具包 |
| `VIP仿真平台用户说明书.pdf` | 全流程使用说明书（7 场景 + 6 项分析） |
| `awesom_VIP开发课题说明书.pdf` | 7 个 IP 课题的功能需求规格 |

安装：`code --install-extension vip-sim-1.0.0.vsix`

## v1.0.0 核心功能

### 仿真全链路
- 图像/视频 → 激励 hex → Verilog 仿真 → 结果还原 → 图像质量分析
- AXI-Stream BFM（source/sink/reg_config），支持随机反压
- DDR 帧缓冲基础设施（几何变换 / 时域降噪类 IP）

### Trae IDE 扩展（Webview GUI）
- 6 卡片布局（图像导入 / IP 参数 / 运行控制 / 媒体预览 / 分析面板 / 状态栏）
- 渐变主题 + 分级按钮 + pill 状态标签 + 呼吸动画
- 6 类分析面板（图像对比 / 差异热力图 / 锐度 / 白平衡 / 直方图 / PSNR）
- 5 个命令 + 环境自检

### Spec 驱动代码生成器（新增）
- `.ip_spec.yaml` → `gen_ip_spec.py` 同时生成 RTL + 金标准 + TB + regdef
- 支持 7 种内置算法类型（passthrough / gain / lut / conv_1d / csc / sharpen / denoise）
- 级联组合 IP：`--chain awb,gamma,sharpen` 自动生成级联 RTL + 金标准函数组合
- RTL 和金标准从同一份规格生成，天然逐位一致

### 金标准逐位比对
- `golden.py` 注册模型，`verify.py` 自动发现并比对
- 支持 frames / tol / frac 三级容差配置
- 级联模型 = 函数组合（`m_awb ∘ m_gamma ∘ m_sharpen`）

## v1.0.0 修复（相对 0.9.x）

| 修复 | 说明 |
|---|---|
| **sim.py regcfg 缺失** | `t_sim()` / `t_video_sim()` 增加 `_gen_regcfg()`，仿真前自动按 regdef.json 生成 regcfg.hex，WIDTH/HEIGHT 用仿真分辨率覆盖 |
| **DPC 回归测试** | `run_regression` 中 `defect_pixel_corr` → `dpc_3x3`（功能检查 / 反压 / 金标准 3 处） |
| **DPC 功能检查 regcfg** | 改用 `reset_regcfg('dpc_3x3', 64, 48)`，不再写空配置 |
| **DPC regdef default** | `IMG_WIDTH` / `IMG_HEIGHT` default 对齐 RTL 复位值（3840 / 2160） |

## 从 v0.9.x 升级

```bash
# 1. 安装新扩展
code --install-extension vip-sim-1.0.0.vsix

# 2. 重启 IDE

# 3. 在已有项目中同步新脚本（可选，覆盖旧版本）
#    Cmd+Shift+P → VIP Sim: 新建仿真项目（选已有目录）
#    或手动复制 template/scripts/ 下的 sim.py / run_regression.py
```

> 向后兼容，现有 IP 无需修改即可工作。
