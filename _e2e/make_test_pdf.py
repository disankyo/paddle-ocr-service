"""生成 E2E 测试用「扫描件」PDF（纯图片、无文字层），用于验证 PaddleOCR 识别链路。"""
import os

from PIL import Image, ImageDraw, ImageFont

OUT = os.path.dirname(os.path.abspath(__file__))
W, H = 1654, 2339  # A4 @ 200 DPI


def make(name, lines, font_path, size):
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, size, index=0)
    y = 220
    for ln in lines:
        d.text((150, y), ln, fill="black", font=font)
        y += int(size * 1.7)
    path = os.path.join(OUT, name)
    img.save(path, "PDF", resolution=200.0)
    print("saved", path)


CJK = r"C:\Windows\Fonts\msyh.ttc"
make(
    "scan_mixed.pdf",
    [
        "PDF OCR 识别测试",
        "第一行：中文识别准确率",
        "第二行：PaddleOCR 引擎",
        "Third line in English",
        "Fourth line: 2026",
    ],
    CJK,
    60,
)

make(
    "scan_en.pdf",
    [
        "PDF OCR TEST",
        "HELLO PADDLE OCR",
        "SEARCHABLE PDF OUTPUT",
        "NUMBER 12345",
    ],
    r"C:\Windows\Fonts\arial.ttf",
    66,
)
