#!/usr/bin/env python3
"""preprocess_custom.py — 自定义预处理算子 (脚手架, 由 Trae AI 按需求填写)

如何使用:
  1. 在 Trae 聊天里用自然语言描述你想对图像/视频做的处理, 例如:
       "把视频整体调暗 30%, 再加轻微的运动模糊"
       "模拟低光照: 降低亮度并加强噪声"
       "给每一帧叠加一个从左到右扫过的暗角"
  2. 让 AI 填写下面的 process() 函数 (只改函数体, 保持签名不变)
  3. 在仿真控制台选 "自定义预处理(AI)" 运行, 或命令行:
       python scripts/preprocess.py -i in.mp4 -o out.mp4 --custom scripts/preprocess_custom.py

约定:
  - frame: H×W×3 的 BGR uint8 numpy 数组 (OpenCV 格式)
  - idx:   帧序号 (0 起), 图像时恒为 0; 可用于做随时间变化的效果
  - rng:   numpy 随机数发生器 (np.random.Generator), 用它保证可复现
  - 返回:  处理后的同形状 uint8 数组 (务必 clip 到 [0,255] 再转 uint8)
"""
import cv2          # noqa: F401  (AI 可能用到)
import numpy as np


def process(frame, idx, rng):
    # ====== 在此填写处理逻辑 (示例: 原样返回) ======
    out = frame
    # 示例: 整体调暗 30%
    #   out = np.clip(frame.astype(np.float64) * 0.7, 0, 255).astype(np.uint8)
    # ===============================================
    return out
