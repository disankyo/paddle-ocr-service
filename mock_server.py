"""
无 Paddle 依赖的契约联调桩（仅用于开发期验证 Java 客户端 ↔ 接口契约）。

它不真正做 OCR，而是把上传图片当成一个“整页文本框”，返回一份结构与真实
PaddleOCR 服务完全一致的响应，便于在没装 Paddle / 离线环境下验证：
  * Java 客户端的多部分上传、JSON 解析
  * PdfOcrService 的 TXT 拼装与可搜索 PDF 文字层叠加流程

运行：python mock_server.py   （默认 8008，绑定 127.0.0.1）
"""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

PORT = 8008


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/health"):
            self._json({"status": "ok", "engines": ["ch", "en"], "paddle_available": False, "mock": True})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self.path.startswith("/ocr"):
            self._json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        # 不解析 multipart 具体内容，只回一份固定结构的响应
        resp = {
            "success": True,
            "width": 2480,
            "height": 3508,
            "lang": "ch",
            "lines": [
                {"text": "MOCK OCR PLACEHOLDER 中文占位", "confidence": 0.99,
                 "bbox": [[200, 300], [2200, 300], [2200, 400], [200, 400]]},
                {"text": "Second line mock content", "confidence": 0.98,
                 "bbox": [[200, 500], [2200, 500], [2200, 600], [200, 600]]},
            ],
            "message": "MOCK SERVER - not real OCR",
        }
        self._json(resp)

    def _json(self, obj, code=200):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"mock paddle-ocr server on :{PORT}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
