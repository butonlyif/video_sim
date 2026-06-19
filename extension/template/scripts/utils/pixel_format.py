"""
像素格式定义与转换工具。
"""

# 格式ID → {name, bit_width, tdata_width, python_dtype, channels}
FORMATS = {
    "RAW8":   {"id": 0, "name": "RAW8",   "bits": 8,  "tdata_bits": 32, "dtype": "uint8",  "channels": 1},
    "RAW10":  {"id": 1, "name": "RAW10",  "bits": 10, "tdata_bits": 32, "dtype": "uint16", "channels": 1},
    "RAW12":  {"id": 2, "name": "RAW12",  "bits": 12, "tdata_bits": 32, "dtype": "uint16", "channels": 1},
    "RGB888": {"id": 3, "name": "RGB888", "bits": 24, "tdata_bits": 32, "dtype": "uint8",  "channels": 3},
    "YUV422": {"id": 4, "name": "YUV422", "bits": 16, "tdata_bits": 32, "dtype": "uint8",  "channels": 3},
    "YUV444": {"id": 5, "name": "YUV444", "bits": 24, "tdata_bits": 32, "dtype": "uint8",  "channels": 3},
}


def get_format(name: str) -> dict:
    """根据名称获取格式信息。"""
    name = name.upper()
    if name not in FORMATS:
        raise ValueError(f"不支持的格式: {name}。支持: {list(FORMATS.keys())}")
    return FORMATS[name]


def image_to_pixels(img, fmt_name: str) -> list:
    """
    将 OpenCV/numpy 图像按 tdata 格式打包为整数列表。

    img: H×W 或 H×W×C 的 numpy 数组 (uint8/uint16)
    返回: list of int (每个值是一个 32bit tdata 字)
    """
    import numpy as np
    fmt = get_format(fmt_name)

    if fmt_name == "RGB888":
        h, w, c = img.shape
        # 打包 {8'd0, R, G, B}
        pixels = []
        for y in range(h):
            for x in range(w):
                r, g, b = int(img[y, x, 2]), int(img[y, x, 1]), int(img[y, x, 0])
                word = (r << 16) | (g << 8) | b
                pixels.append(word)
        return pixels

    elif fmt_name == "YUV422":
        # YUV422 存为 YUYV 交织: {8'd0, Y0, U, V}
        h, w, c = img.shape
        pixels = []
        for y in range(h):
            for x in range(0, w, 2):
                y0 = int(img[y, x, 0])
                u  = int(img[y, x, 1])
                v  = int(img[y, x, 2])
                word = (y0 << 16) | (u << 8) | v
                pixels.append(word)
        return pixels

    elif fmt_name == "YUV444":
        h, w, c = img.shape
        pixels = []
        for y in range(h):
            for x in range(w):
                y_p = int(img[y, x, 0])
                u   = int(img[y, x, 1])
                v   = int(img[y, x, 2])
                word = (y_p << 16) | (u << 8) | v
                pixels.append(word)
        return pixels

    elif fmt_name in ("RAW8", "RAW10", "RAW12"):
        h, w = img.shape[:2]
        if len(img.shape) == 3:
            img = img[:, :, 0]
        pixels = [int(p) & ((1 << fmt["bits"]) - 1) for p in img.flatten()]
        return pixels

    else:
        raise ValueError(f"未处理的格式: {fmt_name}")


def pixels_to_image(pixels: list, fmt_name: str, width: int, height: int):
    """
    将像素整数列表还原为 numpy 图像。

    返回: numpy ndarray (H×W 或 H×W×C), dtype=uint8 或 uint16
    """
    import numpy as np
    fmt = get_format(fmt_name)

    if fmt_name == "RGB888":
        img = np.zeros((height, width, 3), dtype=np.uint8)
        idx = 0
        for y in range(height):
            for x in range(width):
                word = pixels[idx]
                r = (word >> 16) & 0xFF
                g = (word >> 8) & 0xFF
                b = word & 0xFF
                img[y, x] = [b, g, r]  # OpenCV 用 BGR
                idx += 1
        return img

    elif fmt_name == "YUV422":
        img = np.zeros((height, width, 3), dtype=np.uint8)
        idx = 0
        for y in range(height):
            for x in range(0, width, 2):
                word = pixels[idx]
                y0 = (word >> 16) & 0xFF
                u  = (word >> 8) & 0xFF
                v  = word & 0xFF
                img[y, x]   = [y0, u, v]
                img[y, x+1] = [y0, u, v]
                idx += 1
        return img

    elif fmt_name == "YUV444":
        img = np.zeros((height, width, 3), dtype=np.uint8)
        idx = 0
        for y in range(height):
            for x in range(width):
                word = pixels[idx]
                y_p = (word >> 16) & 0xFF
                u   = (word >> 8) & 0xFF
                v   = word & 0xFF
                img[y, x] = [y_p, u, v]
                idx += 1
        return img

    elif fmt_name == "RAW8":
        return np.array(pixels, dtype=np.uint8).reshape((height, width))

    elif fmt_name in ("RAW10", "RAW12"):
        return np.array(pixels, dtype=np.uint16).reshape((height, width))

    else:
        raise ValueError(f"未处理的格式: {fmt_name}")
