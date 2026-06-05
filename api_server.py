#!/usr/bin/env python3
"""番茄小说 API 代理服务器 v2.0

自建 API 代理，部署到云服务器后，桌面客户端通过 HTTP 调用。
完全绕过本地 IP 限制，服务器端处理所有爬虫/解密/验证码。

启动: python api_server.py --port 8080
Docker: docker run -p 8080:8080 -v $(pwd)/downloads:/app/downloads fanqie-api
"""

import sys
import os
import json
import time
import pathlib
import threading
import logging
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from bridge import (
    cmd_search,
    cmd_info,
    cmd_download,
    cmd_download_fanqie,
    cmd_trending,
    cmd_rank,
    cmd_chapters,
    cmd_resolve,
)

try:
    from flask import Flask, request, jsonify, g, make_response
except ImportError:
    print("请安装 Flask: pip install flask")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════
# 日志
# ═══════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("fanqie-api")

# ═══════════════════════════════════════════════════════════
# Flask 应用
# ═══════════════════════════════════════════════════════════
app = Flask(__name__)

# ── CORS 支持 ──
@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        return make_response("", 204)


# ── 简易内存限流 ──
_rate_store: dict[str, list[float]] = {}
_rate_lock = threading.Lock()
RATE_WINDOW = 60       # 60秒窗口
RATE_MAX_GENERAL = 60  # 普通接口 60次/分钟
RATE_MAX_DOWNLOAD = 10 # 下载接口 10次/分钟


def _check_rate(key: str, max_req: int) -> bool:
    now = time.time()
    with _rate_lock:
        times = _rate_store.get(key, [])
        times = [t for t in times if now - t < RATE_WINDOW]
        if len(times) >= max_req:
            return False
        times.append(now)
        _rate_store[key] = times
        return True


def _rate_limit(max_req: int):
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")
    if not _check_rate(ip, max_req):
        return jsonify({"error": "请求过于频繁，请稍后再试", "retry_after": RATE_WINDOW}), 429
    return None


# ── 请求日志 ──
@app.before_request
def log_request():
    g.start = time.time()


@app.after_request
def log_response(response):
    elapsed = time.time() - g.get("start", 0)
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "-")
    log.info(f"{ip} {request.method} {request.path} → {response.status_code} ({elapsed:.2f}s)")
    return response


# ═══════════════════════════════════════════════════════════
# API 路由
# ═══════════════════════════════════════════════════════════

@app.route("/api/search")
def search():
    if rl := _rate_limit(RATE_MAX_GENERAL): return rl
    q = request.args.get("q", "")
    if not q.strip():
        return jsonify({"error": "缺少搜索词"}), 400
    return jsonify(cmd_search(q))


@app.route("/api/resolve")
def resolve():
    if rl := _rate_limit(RATE_MAX_GENERAL): return rl
    title = request.args.get("title", "")
    if not title.strip():
        return jsonify({"error": "缺少书名"}), 400
    return jsonify(cmd_resolve(title))


@app.route("/api/trending")
def trending():
    if rl := _rate_limit(RATE_MAX_GENERAL): return rl
    return jsonify(cmd_trending())


@app.route("/api/rank/<category_id>")
def rank(category_id):
    if rl := _rate_limit(RATE_MAX_GENERAL): return rl
    return jsonify(cmd_rank(category_id))


@app.route("/api/book/<book_id>")
def book_info(book_id):
    if rl := _rate_limit(RATE_MAX_GENERAL): return rl
    return jsonify(cmd_info(book_id))


@app.route("/api/book/<book_id>/chapters")
def chapters(book_id):
    if rl := _rate_limit(RATE_MAX_GENERAL): return rl
    return jsonify(cmd_chapters(book_id))


@app.route("/api/book/<book_id>/download", methods=["POST"])
def download(book_id):
    if rl := _rate_limit(RATE_MAX_DOWNLOAD): return rl
    output_dir = (request.get_json(silent=True) or {}).get("outputDir", "") or None
    log.info(f"下载请求: book_id={book_id}, dir={output_dir}")
    try:
        result = cmd_download(book_id, output_dir)
        return jsonify(result)
    except Exception as e:
        log.exception("下载失败")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/book/<book_id>/download-fanqie", methods=["POST"])
def download_fanqie(book_id):
    if rl := _rate_limit(RATE_MAX_DOWNLOAD): return rl
    output_dir = (request.get_json(silent=True) or {}).get("outputDir", "") or None
    log.info(f"番茄直链下载: book_id={book_id}")
    try:
        result = cmd_download_fanqie(book_id, output_dir)
        if result.get("success") and result.get("path"):
            try:
                with open(result["path"], encoding="utf-8") as f:
                    result["content"] = f.read()
                    result["content_length"] = len(result["content"])
            except Exception:
                pass
        return jsonify(result)
    except Exception as e:
        log.exception("番茄直链下载失败")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({"status": "ok", "version": "2.0.0", "time": datetime.now().isoformat()})


@app.route("/api/stats")
def stats():
    """服务器状态"""
    with _rate_lock:
        ips = len(_rate_store)
    return jsonify({
        "active_ips": ips,
        "version": "2.0.0",
    })


# ═══════════════════════════════════════════════════════════
# 启动
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="番茄小说 API 代理服务器 v2.0")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    print(f"  🍅 番茄小说 API 代理 v2.0")
    print(f"  http://{args.host}:{args.port}")
    print(f"  健康检查: http://localhost:{args.port}/health")
    print(f"  限流: 普通{RATE_MAX_GENERAL}次/分 | 下载{RATE_MAX_DOWNLOAD}次/分")
    app.run(host=args.host, port=args.port, debug=args.debug)
