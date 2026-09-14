# PaddleOCR 识别服务

为 UltimateConverter「PDF OCR」功能提供独立、可水平扩展的 OCR 识别能力。
Java 侧（PDFBox）负责把 PDF 逐页渲染成图片，通过 HTTP 调用本服务完成识别，
拿到「逐行文本 + 置信度 + 四顶点包围盒」后，在 Java 侧恢复阅读顺序并生成可搜索 PDF。

## 接口契约

### `GET /health`
```json
{ "status": "ok", "engines": ["ch","en"], "paddle_available": true }
```

### `POST /ocr` （multipart/form-data）
字段：
- `image`：图片文件（PNG/JPG 等）
- `lang`：语言，默认 `ch`。可选 `en` / `chinese_cht` / `japan` / `korean` / `fr` ...

返回：
```json
{
  "success": true,
  "width": 2480,
  "height": 3508,
  "lang": "ch",
  "lines": [
    { "text": "识别文本", "confidence": 0.98,
      "bbox": [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] }
  ]
}
```
`bbox` 为图像像素坐标、左上原点；Java 侧据此映射到 PDF 点坐标（缩放比 = 页面点宽 / 图片像素宽）。

## 本地运行（Python 3.11 / 3.13）

```bash
python -m venv .venv && .venv/Scripts/activate
pip install -r requirements.txt
# 建议用 8008：宿主机 8000 常被本机打印（C-Lodop）等占用；并绑 127.0.0.1 避免 localhost 走 IPv6 命中别的服务
python -m uvicorn main:app --host 127.0.0.1 --port 8008
```

## 离线 / 无 Paddle 的契约联调桩

```bash
python mock_server.py   # :8008，返回固定结构，不真正识别
```

## Docker

```bash
docker compose up -d    # 构建并启动，宿主机映射到 8008
```

Java 侧通过 `converter.paddle-ocr.service-url` 指向本服务
（本机 `http://127.0.0.1:8008`，同 compose 网络 `http://paddle-ocr:8000`）。
