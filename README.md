# PaddleOCR 识别服务

为 [UltimateConverter](../UltimateConverter) 的「PDF OCR」功能提供**独立、可水平扩展**的 OCR 识别能力。

Java 侧（PDFBox）负责把 PDF **逐页渲染成图片**，通过 HTTP 把图片交给本服务识别；本服务**只认图片、不关心 PDF**，返回「逐行文本 + 置信度 + 四顶点包围盒」；Java 侧再据此恢复阅读顺序、叠加透明文字层，生成**可搜索 PDF**。

```
PDF ──PDFBox 逐页渲染──►  本服务（FastAPI + PaddleOCR）  ──逐行文本 + bbox──►  Java 侧聚合/生成可搜索 PDF
```

> 这样拆分的意义：OCR 引擎可以单独部署、单独扩缩容、单独上 GPU，与 Java 服务解耦；Java 侧只依赖一个 HTTP 契约。

## 接口契约

### `GET /health`

```json
{ "status": "ok", "engines": ["ch"], "paddle_available": true }
```

`engines` 为当前已初始化（被请求过）的语言引擎列表。可用于探活与预热判断。

### `POST /ocr`（multipart/form-data）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `image` | file | 是 | 待识别图片（PNG / JPG 等，能解码即可） |
| `lang` | text | 否 | 语言模型，默认 `ch`；不在白名单内时回退为 `ch` |

响应：

```json
{
  "success": true,
  "width": 2480,
  "height": 3508,
  "lang": "ch",
  "message": null,
  "lines": [
    {
      "text": "识别文本",
      "confidence": 0.98,
      "bbox": [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
    }
  ]
}
```

- `bbox` 为**图像像素坐标、左上原点**。原始四顶点（可能是旋转框）会被规整为左上原点矩形的四角：
  `[[xmin,ymin],[xmax,ymin],[xmax,ymax],[xmin,ymax]]`。
- Java 侧按 `缩放比 = PDF 页面点宽 / 图片像素宽` 把像素坐标映射回 PDF 点坐标。
- 错误时抛 HTTP 400（空图 / 无法解码）或 500（识别异常），`detail` 带简短原因。

**支持语言白名单**（`SUPPORTED_LANGS`）：
`ch`、`en`、`chinese_cht`、`japan`、`korean`、`fr`、`german`、`it`、`es`、`pt`、`ru`、`ar`、`hi`、`ug`、`fa`、`be`、`cs`、`nl`、`sv`、`da`、`no`、`fi`、`tr`、`hu`、`th`、`vi`、`id`。

## 目录结构

```
paddle-ocr-service/
├── main.py            # FastAPI 服务（/health、/ocr），PaddleOCR 封装
├── mock_server.py     # 无 Paddle 环境下的契约联调桩（固定返回结构）
├── requirements.txt   # Python 依赖
├── Dockerfile         # python:3.11-slim + 系统依赖
├── docker-compose.yml # 一键起服务（宿主机 8008 → 容器 8000）
└── _e2e/
    └── make_test_pdf.py  # 生成扫描件测试 PDF/图片（产物被 .gitignore 忽略）
```

## 本地运行（Python 3.11 / 3.13）

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

# 方式一：直接跑（默认 127.0.0.1:8008）
python main.py

# 方式二：uvicorn 显式指定
python -m uvicorn main:app --host 127.0.0.1 --port 8008
```

**为什么默认 8008、绑 127.0.0.1？**
- 宿主机 `8000` 常被本机打印服务（如 C-Lodop）等占用，换成 `8008` 免冲突。
- 绑 `127.0.0.1` 而非 `localhost`：`localhost` 可能先解析到 IPv6 `::1` 而命中别的服务。
- 端口可用环境变量覆盖：`OCR_PORT=8009 python main.py`。

首次识别某个语言的模型会**自动下载并缓存**到 `~/.paddleocr`，之后复用。

### 依赖版本

```
paddlepaddle==3.3.1
paddleocr==3.7.0
fastapi
uvicorn[standard]
python-multipart
opencv-python-headless
Pillow
numpy<2.4
```

`paddlepaddle` 与 `paddleocr` 版本需相互匹配，当前按 **Python 3.11/3.13 + Paddle 3.x** 验证。

## 无 Paddle 环境下的契约联调

不想装 Paddle（体积大、下载模型慢）时，可用桩服务验证 Java 侧链路：

```bash
python mock_server.py     # 默认 127.0.0.1:8008，返回固定结构的 /health 与 /ocr
```

Java 侧 `converter.paddle-ocr.service-url` 指向它即可跑通「上传 → 渲染 → 调用 → 生成可搜索 PDF」全链路，只是文本内容为假数据。

## Docker

```bash
docker compose up -d      # 构建并启动，宿主机 8008 → 容器 8000
```

- 基础镜像 `python:3.11-slim`，装有 `libgl1 / libglib2.0-0 / libgomp1`（PaddleOCR 运行所需）。
- 容器内监听 `0.0.0.0:8000`；compose 映射到宿主机 `8008`。
- 模型缓存挂到命名卷 `paddle-models`（`/root/.paddleocr`），避免每次重建镜像重复下载。
- 需要 GPU 时：Dockerfile 换 `paddlepaddle-gpu` 对应版本并改用 `nvidia/cuda` 基础镜像。

## 与 Java 端（UltimateConverter）的对接

| Java 侧配置 | 值 | 说明 |
|---|---|---|
| `converter.paddle-ocr.service-url` | 本机 `http://127.0.0.1:8008`；同 compose 网络 `http://paddle-ocr:8000` | OCR 服务地址 |
| `converter.paddle-ocr.connect-timeout-ms` | 5000 | 连接超时 |
| `converter.paddle-ocr.timeout-ms` | 120000 | 单次调用读取超时（大图慢机器要留足） |
| `converter.paddle-ocr.max-retries` | 2 | 失败重试 |
| `converter.paddle-ocr.max-concurrent` | 4 | Java 侧并发 OCR 线程数 |
| `converter.ocr-dpi` | 300 | Java 渲染 PDF 页为图的 DPI |

**调用约定（重要）**：Java 侧用 JDK `HttpClient` 发 multipart，**必须显式 `.version(HTTP_1_1)`**——默认对 `http://` 会尝试 h2c 升级，而 uvicorn 不处理，会导致请求被判为 422。

## 实现要点 / 踩过的坑

- **PaddleOCR 3.x 构造参数与 2.x 不同**：用 `use_textline_orientation=True`（取代 2.x 的 `use_angle_cls`），并显式关掉版面方向分类与去畸变（`use_doc_orientation_classify=False`、`use_doc_unwarping=False`）以精简耗时。
- **`enable_mkldnn=False`**：规避 Paddle 3.x 在 Windows/CPU 上 oneDNN + PIR 的崩溃
  `ConvertPirAttribute2RuntimeAttribute not support`。**换模型无效**，只能关 mkldnn。
- **`text_det_limit_side_len=960`**：限制检测输入最长边，CPU 上单页从 ~32s 降到 ~7.6s，识别仍用原分辨率裁剪，质量基本无损。可用环境变量 `OCR_DET_LIMIT_SIDE_LEN` 覆盖。
- **引擎按语言懒加载 + 线程锁**：`get_engine()` 用 `threading.Lock` 保护，避免并发首次初始化重复构建。
- **兼容 3.x 与 2.x 输出**：优先走 3.x 的 `predict()`（`OCRResult` 为 dict 风格，取 `rec_texts / rec_scores / dt_polys`），并对 2.x 的 `ocr(cls=True)` 形式兜底。
- **图片解码双保险**：先 `cv2.imdecode`，失败退回 Pillow 解码再转 BGR。
- 版面理解（多栏、竖排）留在 Java 侧做几何聚行即可，PP-Structure 的表格/区域识别可作为后续增强。

## 相关仓库

| 仓库 | 职责 |
|---|---|
| **UltimateConverter** | 后端（Java / Spring Boot）：渲染 PDF、聚合 OCR 结果、生成可搜索 PDF |
| **ConverterFrontend** | 前端（Vue3 + Vite） |
| **paddle-ocr-service**（本仓库） | OCR 引擎 HTTP 服务（Python / FastAPI） |
