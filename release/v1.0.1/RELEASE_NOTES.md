# VIP Sim v1.0.1 — 发布说明

发布日期：2026-06-24

## 交付内容

| 文件 | 说明 |
|---|---|
| `vip-sim-1.0.1.vsix` | 扩展安装包（54 文件，137KB），内置完整仿真工具包 |

安装：`code --install-extension vip-sim-1.0.1.vsix`

## v1.0.1 变更 — Windows 兼容性增强

### 中文输出修复

| 修复 | 说明 |
|---|---|
| **PYTHONIOENCODING=utf-8** | 扩展在 Windows 上执行 Python 子进程时，自动设置 `PYTHONIOENCODING=utf-8` 环境变量，确保中文输出不再乱码 |
| **ASCII 图标替代** | Windows 上控制台图标从 Unicode（✓✗⚠→...）改为 ASCII（[OK] [FAIL] [WARN] -> ...），避免 GBK 编码错误 |

### 路径处理修复

| 修复 | 说明 |
|---|---|
| **移除多余引号** | 命令行参数中 `INPUT_IMG` / `INPUT_VIDEO` 的值不再被包裹双引号，避免 Windows 上引号被当作路径的一部分 |
| **Makefile 引号过滤** | Makefile 使用 `$(subst ",,$(VAR))` 过滤可能残留的引号 |

## 从 v1.0.0 升级

```bash
# 1. 卸载旧版本
code --uninstall-extension awesom.vip-sim

# 2. 安装新版本
code --install-extension vip-sim-1.0.1.vsix

# 3. 完全退出 Trae / VS Code，重新打开
```

> 向后兼容，现有 IP 和项目无需修改。
