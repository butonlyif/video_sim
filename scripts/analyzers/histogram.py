"""直方图分析模块。"""

import numpy as np
import cv2


def analyze(input_img: np.ndarray, output_img: np.ndarray = None) -> dict:
    """分析 RGB 三通道直方图统计。"""

    def _channel_stats(channel, name):
        ch = channel.flatten().astype(np.float64)
        return {
            "channel": name,
            "mean": round(float(np.mean(ch)), 1),
            "std": round(float(np.std(ch)), 1),
            "median": round(float(np.median(ch)), 1),
            "min": int(ch.min()),
            "max": int(ch.max()),
            "percentile_5": round(float(np.percentile(ch, 5)), 1),
            "percentile_95": round(float(np.percentile(ch, 95)), 1),
        }

    result = {}

    # 输入图统计
    if len(input_img.shape) == 3 and input_img.shape[2] >= 3:
        result["input"] = [
            _channel_stats(input_img[:, :, 2], "R"),
            _channel_stats(input_img[:, :, 1], "G"),
            _channel_stats(input_img[:, :, 0], "B"),
        ]
        input_gray = cv2.cvtColor(input_img, cv2.COLOR_BGR2GRAY)
        result["input_mean"] = round(float(input_gray.mean()), 1)
    else:
        result["input_mean"] = round(float(input_img.mean()), 1)

    # 输出图统计
    if output_img is not None:
        if len(output_img.shape) == 3 and output_img.shape[2] >= 3:
            result["output"] = [
                _channel_stats(output_img[:, :, 2], "R"),
                _channel_stats(output_img[:, :, 1], "G"),
                _channel_stats(output_img[:, :, 0], "B"),
            ]
            output_gray = cv2.cvtColor(output_img, cv2.COLOR_BGR2GRAY)
            result["output_mean"] = round(float(output_gray.mean()), 1)
        else:
            result["output_mean"] = round(float(output_img.mean()), 1)

        # 亮度偏移分析
        result["shift"] = (
            f"亮度{'提升' if result['output_mean'] > result['input_mean'] else '降低'} "
            f"{abs(result['output_mean'] - result['input_mean']):.1f} (均值变化)"
        )

    return result
