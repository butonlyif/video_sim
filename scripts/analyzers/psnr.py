"""PSNR 计算模块。"""

import cv2
import numpy as np


def analyze(input_img: np.ndarray, output_img: np.ndarray = None) -> dict:
    """计算 PSNR，需要输入输出两张图像。"""
    if output_img is None:
        return {"error": "PSNR 需要提供 --output 对比图"}

    a = input_img.astype(np.float64)
    b = output_img.astype(np.float64)

    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]))

    mse = float(np.mean((a - b) ** 2))
    if mse == 0:
        psnr = 100.0
    else:
        max_val = 255.0 if a.max() <= 255 else 4095.0
        psnr = float(20 * np.log10(max_val / np.sqrt(mse)))

    # 逐通道
    ch_psnr = {}
    if len(a.shape) == 3 and a.shape[2] >= 3:
        for i, name in enumerate(["B", "G", "R"]):
            ch_mse = float(np.mean((a[:, :, i] - b[:, :, i]) ** 2))
            if ch_mse == 0:
                ch_psnr[name] = 100.0
            else:
                ch_psnr[name] = round(float(20 * np.log10(max_val / np.sqrt(ch_mse))), 2)

    grade = "优秀" if psnr > 40 else ("良好" if psnr > 30 else ("一般" if psnr > 20 else "差"))

    return {
        "overall": round(psnr, 2),
        "mse": round(mse, 3),
        "channels": ch_psnr,
        "grade": grade,
    }
