"""
Terminal UI 美化模块 — 统一的控制台输出风格。
所有脚本共用，避免各处重复造轮子。
"""

import sys
import os
import shutil
import time
from typing import Optional, List


# ============================================================
# ANSI 色板
# ============================================================

class _Color:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    ITALIC  = "\033[3m"

    BLACK   = "\033[30m"
    RED     = "\033[31m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    BLUE    = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN    = "\033[36m"
    WHITE   = "\033[37m"

    BG_BLACK   = "\033[40m"
    BG_RED     = "\033[41m"
    BG_GREEN   = "\033[42m"
    BG_YELLOW  = "\033[43m"
    BG_BLUE    = "\033[44m"
    BG_MAGENTA = "\033[45m"
    BG_CYAN    = "\033[46m"
    BG_WHITE   = "\033[47m"

C = _Color

# 自动检测终端是否支持色彩（管道/重定向时关闭）
_has_color = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    """包裹 ANSI 转义码；不可用时原样返回。"""
    return f"{code}{text}{C.RESET}" if _has_color else text


def green(s):    return _c(C.GREEN, s)
def red(s):      return _c(C.RED, s)
def yellow(s):   return _c(C.YELLOW, s)
def blue(s):     return _c(C.BLUE, s)
def magenta(s):  return _c(C.MAGENTA, s)
def cyan(s):     return _c(C.CYAN, s)
def bold(s):     return _c(C.BOLD, s)
def dim(s):      return _c(C.DIM, s)


# ============================================================
# 图标（不依赖 emoji 字体，用 ANSI + 符号替代）
# ============================================================

ICON_OK     = green("✓")
ICON_FAIL   = red("✗")
ICON_WARN   = yellow("⚠")
ICON_INFO   = blue("ℹ")
ICON_GEAR   = cyan("⚙")
ICON_CLOCK  = dim("⏳")
ICON_ARROW  = dim("→")
ICON_BULLET = dim("•")

# ============================================================
# 终端宽度
# ============================================================

def term_width() -> int:
    return shutil.get_terminal_size().columns


# ============================================================
# 基础输出原语
# ============================================================

def info(msg: str):
    """一般信息。"""
    print(f"  {ICON_INFO}  {msg}")


def success(msg: str):
    """成功消息。"""
    print(f"  {ICON_OK}  {green(msg)}")


def warn(msg: str):
    """警告消息。"""
    print(f"  {ICON_WARN}  {yellow(msg)}")


def error(msg: str):
    """错误消息。"""
    print(f"  {ICON_FAIL}  {red(msg)}", file=sys.stderr)


def step(no: int, msg: str):
    """步骤标题。"""
    print(f"\n  {bold(cyan(f'[{no}]'))}  {bold(msg)}")


def sub(msg: str):
    """子项信息。"""
    print(f"      {ICON_ARROW}  {dim(msg)}")


# ============================================================
# 标题 / 分隔线
# ============================================================

def h1(title: str, width: int = 0):
    """一级标题（带框线）。"""
    w = width or min(term_width(), 72)
    # 去掉 ANSI 码的长度
    inner = f"  {title}  "
    bar = "═" * ((w - len(inner)) // 2)
    print(f"\n{cyan(bar + inner + bar)}")


def h2(title: str):
    """二级标题（下划线）。"""
    print(f"\n  {bold(title)}")
    print(f"  {dim('─' * (min(term_width(), 72) - 2))}")


def divider(char: str = "─"):
    """一条水平分隔线。"""
    print(f"  {dim(char * (min(term_width(), 72) - 2))}")


# ============================================================
# 键值对
# ============================================================

def kv(key: str, value: str, indent: int = 4):
    """对齐的键值对。"""
    pad = " " * indent
    print(f"{pad}{bold(key + ':')} {cyan(value)}")


# ============================================================
# 表格
# ============================================================

def table(headers: List[str], rows: List[List[str]]):
    """打印简单的对齐表格。"""
    if not rows:
        return
    all_rows = [headers] + rows
    col_widths = []
    for i in range(len(headers)):
        col_widths.append(max(len(r[i]) for r in all_rows))

    def fmt_row(row):
        cells = "  │  ".join(
            bold(row[i].ljust(col_widths[i])) if row is headers else row[i].ljust(col_widths[i])
            for i in range(len(headers))
        )
        print(f"  │  {cells}  │")

    sep = "─┼─".join("─" * w for w in col_widths)
    print(f"  ┌─ {sep.replace('─┼─', '─┬─')} ─┐")
    fmt_row(headers)
    print(f"  ├─ {sep} ─┤")
    for row in rows:
        fmt_row(row)
    print(f"  └─ {sep.replace('─┼─', '─┴─')} ─┘")


# ============================================================
# 进度条
# ============================================================

class Progress:
    """轻量进度条，不依赖第三方库。

    用法:
        p = Progress("处理中", total=2073600)
        for pixel in pixels:
            p.update(1)
        p.done()
    """

    def __init__(self, label: str, total: int, width: int = 30):
        self.label = label
        self.total = max(total, 1)
        self.width = width
        self.current = 0
        self._start = time.time()
        self._drawn = False
        # 仅在终端环境下显示
        self._enabled = _has_color

    def update(self, n: int = 1):
        self.current += n
        if self._enabled:
            self._draw()

    def _draw(self):
        pct = min(self.current / self.total, 1.0)
        filled = int(self.width * pct)
        bar = f"{C.BG_CYAN}{' ' * filled}{C.RESET}{dim('░' * (self.width - filled))}"
        elapsed = time.time() - self._start
        if pct > 0:
            eta = elapsed / pct * (1 - pct)
            time_str = f" {elapsed:.1f}s / ~{eta:.1f}s"
        else:
            time_str = ""

        sys.stdout.write(
            f"\r  {ICON_GEAR}  {self.label}  {bar}  {pct*100:5.1f}%{dim(time_str)}"
        )
        sys.stdout.flush()
        self._drawn = True

    def done(self):
        elapsed = time.time() - self._start
        if self._drawn:
            sys.stdout.write(f"\r  {ICON_OK}  {self.label}  {green('完成')}  {dim(f'{elapsed:.1f}s')}\033[K\n")
        elif self._enabled:
            sys.stdout.write(f"\r  {ICON_OK}  {self.label}  {green('完成')}\033[K\n")


class Spinner:
    """等待旋转器，用于不确定进度的操作。"""

    _FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, label: str):
        self.label = label
        self._i = 0
        self._enabled = _has_color

    def tick(self):
        if not self._enabled:
            return
        frame = cyan(self._FRAMES[self._i % len(self._FRAMES)])
        self._i += 1
        sys.stdout.write(f"\r  {frame}  {self.label}")
        sys.stdout.flush()

    def done(self, ok: bool = True):
        icon = ICON_OK if ok else ICON_FAIL
        msg = green("完成") if ok else red("失败")
        sys.stdout.write(f"\r  {icon}  {self.label}  {msg}\n")


# ============================================================
# 顶部横幅（程序入口）
# ============================================================

def banner(name: str, version: str = "1.0.0", desc: str = ""):
    """打印程序起始横幅。"""
    w = min(term_width(), 60)
    border = cyan("▔" * w)
    print(f"\n{border}")
    print(f"  {bold(name)}  {dim(f'v{version}')}")
    if desc:
        print(f"  {dim(desc)}")
    print(border)


# ============================================================
# 底部摘要
# ============================================================

def footer(ok: bool = True, elapsed: float = 0):
    """打印程序结束摘要。"""
    print()
    if ok:
        print(f"  {ICON_OK}  {green('结束')}  {dim(f'耗时 {elapsed:.1f}s')}")
    else:
        print(f"  {ICON_FAIL}  {red('异常退出')}  {dim(f'耗时 {elapsed:.1f}s')}")
    print()
