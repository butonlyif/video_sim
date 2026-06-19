"""Gamma 曲线分析模块。"""

import numpy as np
import cv2

# 标准 18% 灰度阶梯目标值（markdown灰度条）  
GRAY_STEPS = [0, 16, 32, 48, 64, 80, 96, 112, 128, 144, 160, 176, 192, 208, 224, 240, 255]


def analyze(input_img: np.ndarray, output_img: np.ndarray = None,
            target_gamma: float = 2.2) -> dict:
    """分析 Gamma 曲线，对比实际值与目标值。"""
    if output_img is None:
        return {"error": "Gamma 分析需要提供 --output 对比图"}

    in_gray = cv2.cvtColor(input_img, cv2.COLOR_BGR2GRAY) if len(input_img.shape) == 3 else input_img
    out_gray = cv2.cvtColor(output_img, cv2.COLOR_BGR2GRAY) if len(output_img.shape) == 3 else output_img

    in_gray = in_gray.astype(np.float64)
    out_gray = out_gray.astype(np.float64)

    # 测量: 对每个输入灰度级，找对应区域的输出均值
    measured = []
    for step in GRAY_STEPS:
        mask = (in_gray >= step - 1) & (in_gray <= step + 1)
        if mask.sum() > 50:
            avg_out = float(out_gray[mask].mean())
            measured.append((step, avg_out))

    if not measured:
        return {"error": "无法测量 Gamma 曲线（输入图灰度级不够丰富）"}

    # 拟合 Gamma: output = (input/255)^(1/gamma) * 255
    # 线性回归 log(output/255) = (1/gamma) * log(input/255)
    steps = np.array([m[0] for m in measured if m[0] > 0])
    outs  = np.array([m[1] for m in measured if m[0] > 0])

    if len(steps) < 3:
        return {"error": "有效采样点不足"}

    x = np.log(steps / 255.0)
    y = np.log(np.clip(outs, 1, 255) / 255.0)
    slope = float(np.sum(x * y) / np.sum(x * x))
    measured_gamma = round(1.0 / slope, 2) if slope != 0 else 0

    delta = round(abs(measured_gamma - target_gamma), 2)
    grade = "优秀" if delta < 0.05 else ("良好" if delta < 0.1 else ("一般" if delta < 0.3 else "偏差大"))

    return {
        "measured": measured_gamma,
        "target": target_gamma,
        "delta": delta,
        "grade": grade,
        "sample_points": len(measured),
    }
