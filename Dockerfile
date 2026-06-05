# 番茄小说 API 代理服务器 — Docker 部署
FROM python:3.11-slim

WORKDIR /app

# 安装依赖（Flask + requests 即可，轻量化）
RUN pip install --no-cache-dir flask requests

# 复制核心代码
COPY bridge.py api_server.py charset.json ./

# 创建下载目录
RUN mkdir -p /app/downloads

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

EXPOSE 8080

# 以非 root 运行（如果不需要写 downloads 到宿主机则用 nobody）
# 需要写 downloads 则保持 root 或挂载 volume
CMD ["python", "api_server.py", "--port", "8080"]
