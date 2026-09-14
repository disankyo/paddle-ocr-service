"""
PaddleOCR HTTP 服务（FastAPI）
================================

为 UltimateConverter 的「PDF OCR」功能提供独立、可水平扩展的 OCR 识别能力。
设计要点：

* 解耦：Java 侧（PDFBox 负责分页渲染）只负责把每一页 PDF 渲染成图片，
  通过 HTTP 把图片交给本服务做识别；本服务不关心 PDF，只认图片。
* 多语言：通过 `lang` 表单字段选择 PaddleOCR 预置语言模型（ch / en / chinese_cht / japan ...），
  引擎按语言懒加载并缓存，避免重复初始化开销。
* 返回结构：逐行文本 + 置信度 + 四顶点包围盒（图像像素坐标，左上原点）。
  Java 侧据此恢复阅读顺序并叠加透明文字层生成「可搜索 PDF」。
* 版面：OCR 返回的是带坐标的文本行，Java 侧按坐标做几何聚行即可得到稳定的阅读顺序，
  足以覆盖多栏、竖排等常见版面；PP-Structure 表格/区域识别可作为后续增强。

启动：
    python -m uvicorn main:app --host 0.0.0.0 --port 8000

健康检查：
    GET  /health
识别：
    POST /ocr  （multipart：image=图片文件, lang=ch|en|...）
"""

from __future__ import annotations

import io
import threading
from typing import List, Optional

import cv2
import numpy as np
import os
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from paddleocr import PaddleOCR

app = FastAPI(title="PaddleOCR Service", version="1.0.0")

# 检测输入的最长边限制（像素）。降低它可显著加速（CPU 上尤为明显），
# 识别仍使用原分辨率裁剪，因此对清晰文本质量影响很小。默认 960，可用环境变量覆盖。
DET_LIMIT_SIDE_LEN = int(os.environ.get("OCR_DET_LIMIT_SIDE_LEN", "960"))

# ---- 引擎缓存（按语言懒加载，线程安全） ----
_ENGINES: dict[str, "PaddleOCR"] = {}
_ENGINES_LOCK = threading.Lock()

# PaddleOCR 预置语言白名单（与服务端已下载/可下载的模型对应）
SUPPORTED_LANGS = {
    "ch", "en", "chinese_cht", "japan", "korean", "fr", "german",
    "it", "es", "pt", "ru", "ar", "hi", "ug", "fa", "be", "cs",
    "nl", "sv", "da", "no", "fi", "tr", "hu", "th", "vi", "id",
}


def get_engine(lang: str) -> "PaddleOCR":
    """按语言获取（必要时初始化并缓存）PaddleOCR 引擎。"""
    if lang not in SUPPORTED_LANGS:
        lang = "ch"
    with _ENGINES_LOCK:
        if lang not in _ENGINES:
            # PaddleOCR 3.x 构造参数与 2.x 不同：use_textline_orientation 取代 use_angle_cls；
            # enable_mkldnn=False 用于规避 Paddle 3.x 在 Windows/CPU 上 oneDNN+PIR 的
            # "ConvertPirAttribute2RuntimeAttribute not support" 崩溃。
            _ENGINES[lang] = PaddleOCR(
                lang=lang,
                use_textline_orientation=True,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                enable_mkldnn=False,
                text_det_limit_type="max",
                text_det_limit_side_len=DET_LIMIT_SIDE_LEN,
            )
        return _ENGINES[lang]


def _decode_image(data: bytes) -> np.ndarray:
    """把上传的字节解码为 BGR numpy 数组（PaddleOCR 期望的输入格式）。"""
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        # 退路：用 Pillow 解码再转 BGR
        from PIL import Image
        pil = Image.open(io.BytesIO(data)).convert("RGB")
        img = cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)
    return img


def _normalize_bbox(points) -> List[List[int]]:
    """把任意四顶点（可能旋转）规整为左上原点矩形的 4 个角点：
    [[xmin,ymin],[xmax,ymin],[xmax,ymax],[xmin,ymax]]。"""
    xs = [int(p[0]) for p in points]
    ys = [int(p[1]) for p in points]
    return [
        [min(xs), min(ys)],
        [max(xs), min(ys)],
        [max(xs), max(ys)],
        [min(xs), max(ys)],
    ]


def _field(res, key, default=None):
    """从 PaddleOCR 3.x 的 OCRResult（dict 风格）或普通对象里取值。"""
    try:
        return res[key]
    except Exception:
        return getattr(res, key, default)


def run_ocr(lang: str, img: np.ndarray):
    """调用 PaddleOCR 识别，统一返回 [(bbox4pts, text, score), ...]。

    以 PaddleOCR 3.x 的 predict() 为主：OCRResult 为 dict 风格，
    含 rec_texts / rec_scores / dt_polys；并对 2.x 的 ocr() 形式做兜底。
    """
    engine = get_engine(lang)

    # ---- PaddleOCR 3.x 的 predict()：OCRResult 为 dict 风格 ----
    predict = getattr(engine, "predict", None)
    if callable(predict):
        results = predict(img)
        out: List[tuple] = []
        for res in results or []:
            texts = _field(res, "rec_texts")
            scores = _field(res, "rec_scores")
            polys = _field(res, "dt_polys")
            if polys is None:
                polys = _field(res, "rec_polys")
            if not texts:
                continue
            for i in range(len(texts)):
                s = scores[i] if scores is not None and i < len(scores) else 1.0
                if polys is None or i >= len(polys):
                    continue
                out.append((_normalize_bbox(polys[i]), str(texts[i]), float(s)))
        return out

    # ---- 2.x 的 ocr() ----
    raw = engine.ocr(img, cls=True)
    out = []
    if not raw:
        return out
    # ocr() 对单张图返回 [ [ [bbox], (text, score) ], ... ]（外层是“页”列表）
    page = raw[0] if (isinstance(raw, list) and len(raw) > 0 and isinstance(raw[0], list)) else raw
    for item in page or []:
        if not item or len(item) < 2:
            continue
        bbox_pts, text_score = item[0], item[1]
        text = text_score[0] if isinstance(text_score, (list, tuple)) else text_score
        score = text_score[1] if isinstance(text_score, (list, tuple)) and len(text_score) > 1 else 1.0
        out.append((_normalize_bbox(bbox_pts), str(text), float(score)))
    return out


# ---- 响应模型 ----
class OcrLine(BaseModel):
    text: str
    confidence: float
    bbox: List[List[int]]  # [[xmin,ymin],[xmax,ymin],[xmax,ymax],[xmin,ymax]]


class OcrResponse(BaseModel):
    success: bool
    width: int = 0
    height: int = 0
    lang: str = ""
    lines: List[OcrLine] = []
    message: Optional[str] = None


@app.get("/health")
def health():
    return {"status": "ok", "engines": list(_ENGINES.keys()), "paddle_available": True}


@app.post("/ocr", response_model=OcrResponse)
def ocr_endpoint(image: UploadFile = File(...), lang: str = Form("ch")):
    data = image.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty image")

    try:
        img = _decode_image(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"无法解码图片: {e}")

    h, w = img.shape[:2]
    try:
        rows = run_ocr(lang, img)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR 识别失败: {e}")

    lines = [
        OcrLine(text=t, confidence=float(s), bbox=bbox) for (bbox, t, s) in rows
    ]
    return OcrResponse(success=True, width=w, height=h, lang=lang, lines=lines)


if __name__ == "__main__":
    import uvicorn

    # 直接 `python main.py` 运行时使用；端口默认 8008（避开本机 8000 常被打印服务等占用），
    # 并绑 127.0.0.1 避免 localhost 走 IPv6 ::1 命中别的服务。
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("OCR_PORT", "8008")), workers=1)
