# VIP 仿真验证系统 — 顶层 Makefile (薄封装)
#
# 真正的构建编排在 scripts/sim.py (纯 Python, 跨平台, 不依赖 Unix shell)。
# 本 Makefile 仅为 Mac/Linux 习惯 `make` 的用户转发命令; Windows / 扩展
# 直接调用 `python scripts/sim.py <target> KEY=VALUE ...`, 无需安装 make。
#
# 仿真工具: Icarus Verilog (iverilog/vvp)

PYTHON ?= python3

# 变量默认值 (与 scripts/sim.py 的 DEFAULTS 保持一致)
IP          ?= passthrough
WIDTH       ?= 64
HEIGHT      ?= 48
FRAMES      ?= 1
FORMAT      ?= RGB888
INPUT_IMG   ?= sim/testdata/test_input.png
INPUT_VIDEO ?= sim/testdata/test_input.mp4
FPS         ?= 30
WAVE        ?= 0
VIDEO       ?= 0

# 转发给 sim.py 的变量 (KEY=VALUE)
ARGS = IP=$(IP) WIDTH=$(WIDTH) HEIGHT=$(HEIGHT) FRAMES=$(FRAMES) \
       FORMAT=$(FORMAT) INPUT_IMG=$(INPUT_IMG) INPUT_VIDEO=$(INPUT_VIDEO) \
       FPS=$(FPS) WAVE=$(WAVE) VIDEO=$(VIDEO)

TARGETS = gen_stimulus sim gen_output analyze verify check \
          video_stimulus video_sim video_output video \
          regression view_wave clean all

.PHONY: $(TARGETS)

$(TARGETS):
	$(PYTHON) scripts/sim.py $@ $(ARGS)
