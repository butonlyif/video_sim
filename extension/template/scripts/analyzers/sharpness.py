"""锐度分析模块。"""

import cv2
import numpy as np


def analyze(input_img: np.ndarray, output_img: np.ndarray = None) -> dict:
    """分析图像锐度，返回量化指标。"""
    img = output_img if output_img is not None else input_img
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    gray = gray.astype(np.float64)

    # Laplacian 方差（最常用的锐度指标）
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    lap_var = float(lap.var())

    # Sobel 梯度均值
    sobel_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0)
    sobel_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1)
    sobel_mag = np.sqrt(sobel_x ** 2 + sobel_y ** 2)
    sobel_mean = float(sobel_mag.mean())

    # Tenengrad
    tenengrad = float(np.sum(sobel_mag ** 2))

    # 等级评定
    if lap_var < 50:
        grade = "模糊"
    elif lap_var < 200:
        grade = "一般"
    elif lap_var < 800:
        grade = "良好"
    elif lap_var < 2000:
        grade = "优秀"
    else:
        grade = "极佳"

    return {
        "laplacian_variance": round(lap_var, 1),
        "sobel_mean": round(sobel_mean, 3),
        "tenengrad": round(tenengrad, 0),
        "grade": grade,
    }
