"""白平衡分析模块。"""

import cv2
import numpy as np


def analyze(input_img: np.ndarray, output_img: np.ndarray = None) -> dict:
    """基于灰度世界假说分析白平衡。"""
    img = output_img if output_img is not None else input_img
    if len(img.shape) < 3 or img.shape[2] < 3:
        return {"error": "需要 RGB 彩色图像"}

    b, g, r = cv2.split(img.astype(np.float64))

    avg_r = float(np.mean(r))
    avg_g = float(np.mean(g))
    avg_b = float(np.mean(b))
    gray = (avg_r + avg_g + avg_b) / 3.0

    r_gain = gray / avg_r if avg_r > 0 else 1.0
    g_gain = 1.0
    b_gain = gray / avg_b if avg_b > 0 else 1.0

    # 色温估算（非常粗略：基于 R/B 比率）
    rb_ratio = avg_r / avg_b if avg_b > 0 else 1.0
    # 粗略映射：< 0.9 冷色, 0.9-1.1 中性, > 1.1 暖色
    if rb_ratio < 0.85:
        bias = "偏冷(蓝)"
    elif rb_ratio > 1.15:
        bias = "偏暖(黄)"
    else:
        bias = "中性"

    # 找最亮区域评估白点
    gray_img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    percentile_95 = np.percentile(gray_img, 95)
    white_mask = gray_img >= percentile_95
    if white_mask.sum() > 100:
        white_region = img[white_mask]
        white_r = float(np.mean(white_region[:, 2]))
        white_g = float(np.mean(white_region[:, 1]))
        white_b = float(np.mean(white_region[:, 0]))
    else:
        white_r, white_g, white_b = 0, 0, 0

    return {
        "r_gain": round(r_gain, 3),
        "g_gain": round(g_gain, 3),
        "b_gain": round(b_gain, 3),
        "avg_r": round(avg_r, 1),
        "avg_g": round(avg_g, 1),
        "avg_b": round(avg_b, 1),
        "rb_ratio": round(rb_ratio, 3),
        "bias": bias,
        "white_point": {
            "r": round(white_r, 1),
            "g": round(white_g, 1),
            "b": round(white_b, 1),
        },
    }
