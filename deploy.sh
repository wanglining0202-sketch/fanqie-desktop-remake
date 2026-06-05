#!/bin/bash
# 番茄小说 API 代理 — 一键部署脚本 (Ubuntu/Debian)
# 用法: bash deploy.sh [port]
# 前提: 服务器需能访问 fanqienovel.com（国内服务器）

set -e

PORT=${1:-8080}

echo "🍅 番茄小说 API 代理 v2.0 — 部署"
echo "=============================="

# 检查 Python
if ! command -v python3 &>/dev/null; then
    echo "安装 Python3..."
    sudo apt-get update -qq && sudo apt-get install -y -qq python3 python3-pip
fi

# 安装依赖
pip3 install flask requests --quiet

# 部署目录
sudo mkdir -p /opt/fanqie-api
sudo cp bridge.py api_server.py charset.json /opt/fanqie-api/
sudo mkdir -p /opt/fanqie-api/downloads

# systemd 服务
sudo tee /etc/systemd/system/fanqie-api.service > /dev/null << EOF
[Unit]
Description=番茄小说 API 代理
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/fanqie-api
ExecStart=/usr/bin/python3 api_server.py --port ${PORT}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 启动
sudo systemctl daemon-reload
sudo systemctl enable fanqie-api
sudo systemctl restart fanqie-api

sleep 2

echo ""
echo "✅ 部署完成!"
echo "   健康检查: http://localhost:${PORT}/health"
echo "   日志: sudo journalctl -u fanqie-api -f"
echo ""
echo "⚠️  如果服务器在国内，测试: curl http://localhost:${PORT}/api/trending"
echo ""
echo "📱 在你的 fanqie-desktop-remake 设置环境变量:"
echo "   set REMOTE_API=http://你的服务器IP:${PORT}"
echo "   然后: node server.js"
