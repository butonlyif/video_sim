# VIP 仿真验证系统 — 顶层 Makefile
# 仿真工具: Icarus Verilog (iverilog/vvp)

# Python: Windows 用 python, Mac/Linux 优先用 .venv
PYTHON := python

# OS 检测
IS_WIN := false

# IP 选择
IP ?= passthrough

# 分辨率 / 格式 (日常回归用小分辨率, 见 DESIGN_SPEC.md iverilog 性能约定)
# WIDTH/HEIGHT = 输入维度。
WIDTH  ?= 64
HEIGHT ?= 48
FRAMES ?= 1
FORMAT ?= RGB888

# 输出维度 / IP 分类由 rtl/$(IP)/ip.json 推导(平台改进 #2/#3)。
# 缺省恒等(OUT=IN) + pointwise, 现有 IP 不受影响。
OUT_WIDTH  := $(shell $(PYTHON) scripts/ip_manifest.py --ip $(IP) --in-w $(WIDTH) --in-h $(HEIGHT) --get out_w)
OUT_HEIGHT := $(shell $(PYTHON) scripts/ip_manifest.py --ip $(IP) --in-w $(WIDTH) --in-h $(HEIGHT) --get out_h)
CATEGORY   := $(shell $(PYTHON) scripts/ip_manifest.py --ip $(IP) --get category)

# 输入图像
INPUT_IMG ?= sim/testdata/test_input.png

# 视频输入 / 帧率 (视频模式)
INPUT_VIDEO ?= sim/testdata/test_input.mp4
FPS ?= 30

# 波形: make sim WAVE=1
ifeq ($(WAVE),1)
PLUSARGS = +WAVE
endif

# 视频模式: make video IP=.. INPUT_VIDEO=.. FRAMES=N → 流式读多帧
ifeq ($(VIDEO),1)
STREAM_PARAM = -Ptb_$(IP).C_STREAM=1
endif

# 路径
RTL_DIR    = rtl/$(IP)
# 使用 Python glob 替代 find 命令, 兼容 Windows
RTL_ALL    = $(shell $(PYTHON) -c "import glob; print(' '.join(glob.glob('rtl/**/*.v', recursive=True)))")
SIM_DIR    = sim
COMMON_DIR = $(SIM_DIR)/common
OUT_DIR    = output

TB_PARAMS = -Ptb_$(IP).C_WIDTH=$(WIDTH) \
            -Ptb_$(IP).C_HEIGHT=$(HEIGHT) \
            -Ptb_$(IP).C_FRAMES=$(FRAMES)

# 维度变换 IP: 给 sink 注入输出维度(平台改进 #2)。仅当 OUT≠IN 时注入,
# 故其 tb 须声明 C_OUT_WIDTH/C_OUT_HEIGHT; 恒等 IP 不注入, 现有 tb 不受影响。
ifneq ($(OUT_WIDTH)x$(OUT_HEIGHT),$(WIDTH)x$(HEIGHT))
TB_PARAMS += -Ptb_$(IP).C_OUT_WIDTH=$(OUT_WIDTH) \
             -Ptb_$(IP).C_OUT_HEIGHT=$(OUT_HEIGHT)
endif

# === 目标 ===

.PHONY: gen_stimulus sim gen_output analyze check verify regression view_wave all clean

# 金标准比对: 用 Python 参考模型生成期望输出并逐字比对仿真结果 (PASS/FAIL)
verify:
	$(PYTHON) scripts/verify.py --ip $(IP) -W $(WIDTH) -H $(HEIGHT) \
	    --json $(OUT_DIR)/reports/$(IP)_verify.json

# 全 IP 回归测试 (冒烟 + 功能性检查 + 随机反压)
# Mac/Linux 使用 bash 脚本, Windows 使用 Python 脚本
regression:
	$(PYTHON) scripts/run_regression.py

gen_stimulus: $(INPUT_IMG)
	$(PYTHON) scripts/gen_stimulus.py -i $(INPUT_IMG) \
	    -o $(SIM_DIR)/testdata/stimulus.hex \
	    -f $(FORMAT) -W $(WIDTH) -H $(HEIGHT)

sim: gen_stimulus
	mkdir -p $(OUT_DIR)/waves
	rm -f $(SIM_DIR)/testdata/result.hex
	cd . && iverilog -g2012 -o $(OUT_DIR)/$(IP).vvp $(TB_PARAMS) $(STREAM_PARAM) $(COMMON_DIR)/*.v $(RTL_ALL) $(SIM_DIR)/tests/tb_$(IP).v
	vvp $(OUT_DIR)/$(IP).vvp $(PLUSARGS)

# === 视频模式 (导入MP4 → 流式逐帧仿真 → 导出MP4) ===
.PHONY: video_stimulus video_sim video_output video

video_stimulus: $(INPUT_VIDEO)
	$(PYTHON) scripts/gen_video_stimulus.py -i $(INPUT_VIDEO) \
	    -o $(SIM_DIR)/testdata/stimulus.hex \
	    -W $(WIDTH) -H $(HEIGHT) --max-frames $(FRAMES)

video_sim: video_stimulus
	mkdir -p $(OUT_DIR)/waves
	rm -f $(SIM_DIR)/testdata/result.hex
	cd . && iverilog -g2012 -o $(OUT_DIR)/$(IP).vvp $(TB_PARAMS) -Ptb_$(IP).C_STREAM=1 $(COMMON_DIR)/*.v $(RTL_ALL) $(SIM_DIR)/tests/tb_$(IP).v
	vvp $(OUT_DIR)/$(IP).vvp $(PLUSARGS)

video_output:
	mkdir -p $(OUT_DIR)/video
	$(PYTHON) scripts/gen_video_output.py \
	    -i $(SIM_DIR)/testdata/result.hex \
	    -o $(OUT_DIR)/video/$(IP)_output.mp4 \
	    -W $(WIDTH) -H $(HEIGHT) --frames $(FRAMES) --fps $(FPS)

video: video_sim video_output

gen_output:
	mkdir -p $(OUT_DIR)/images
	$(PYTHON) scripts/gen_output.py \
	    -i $(SIM_DIR)/testdata/result.hex \
	    -o $(OUT_DIR)/images/$(IP)_output.png \
	    -f $(FORMAT) -W $(OUT_WIDTH) -H $(OUT_HEIGHT) --frames $(FRAMES)

# 分析: 以 stimulus.hex 还原图为参考基准 (即 DUT 实际输入, 输入维度)
# 输出图按输出维度还原; --category 决定是否启用逐像素对齐指标(平台改进 #3)
analyze:
	mkdir -p $(OUT_DIR)/reports
	$(PYTHON) scripts/gen_output.py \
	    -i $(SIM_DIR)/testdata/stimulus.hex \
	    -o $(OUT_DIR)/images/$(IP)_input.png \
	    -f $(FORMAT) -W $(WIDTH) -H $(HEIGHT)
	$(PYTHON) scripts/analyze.py \
	    --input  $(OUT_DIR)/images/$(IP)_input.png \
	    --output $(OUT_DIR)/images/$(IP)_output.png \
	    --report $(OUT_DIR)/reports/$(IP)_report.json \
	    --diff   $(OUT_DIR)/images/$(IP)_diff.png \
	    --category $(CATEGORY)

# 闭环自检: 直通 DUT 时输出应与激励完全一致
# 使用 Python diff 替代 Unix diff 命令, 兼容 Windows
check:
	$(PYTHON) -c "import sys; f1=open('$(SIM_DIR)/testdata/stimulus.hex').read(); f2=open('$(SIM_DIR)/testdata/result.hex').read(); sys.exit(0 if f1==f2 else 1)"
	@if errorlevel 1 (echo CHECK FAIL: result.hex differs from stimulus.hex) else (echo CHECK PASS: result.hex matches stimulus.hex)

# 波形查看: 在 Trae/VS Code 中打开 VCD (VaporView 扩展接管)
# 注: brew 的 gtkwave cask 已废弃, 与 macOS 14+ 不兼容
view_wave:
	@echo "请在 Trae 中打开: $(OUT_DIR)/waves/$(IP).vcd"

all: sim gen_output analyze

clean:
	rm -rf $(OUT_DIR)/$(IP).vvp $(OUT_DIR)/images $(OUT_DIR)/waves $(SIM_DIR)/testdata/stimulus.hex $(SIM_DIR)/testdata/result.hex
