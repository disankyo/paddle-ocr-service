# PaddleOCR HTTP 服务镜像
# 使用 Python 3.11（Paddle 3.x 官方支持），如需 GPU 可换成 paddlepaddle-gpu 对应基础镜像。
FROM python:3.11-slim

WORKDIR /app

# 系统依赖：PaddleOCR 运行需要 libgl 等
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# 模型默认在首次识别时自动下载并缓存到 ~/.paddleocr；可挂载该目录避免重复下载
ENV PADDLE_HOME=/root/.paddleocr
VOLUME ["/root/.paddleocr"]

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
