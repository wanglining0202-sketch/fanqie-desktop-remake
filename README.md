# 番茄小说下载器 — 自建 API 代理版

搜索、下载番茄小说，支持 TXT/EPUB 格式。带桌面风格 Web UI。

## 架构

```
┌─────────────────────┐      HTTP       ┌──────────────────┐     直连     ┌──────────┐
│ fanqie-desktop-remake│ ──────────────→ │ api_server.py    │ ──────────→ │ fanqie   │
│ (前端 UI · 本地)     │ ←────────────── │ (API 代理 · 云端) │ ←────────── │ novel.com│
└─────────────────────┘      JSON       └──────────────────┘              └──────────┘
```

- **前端**：`index.html` + `app.js` + `styles.css`
- **服务层**：`server.js`（Node.js 本地开发服务器）
- **代理层**：`api_server.py`（Flask，部署到云服务器）
- **抓取层**：`bridge.py`（搜索/解析/下载/解密）

## 快速开始（本地使用）

```bash
# 1. 安装依赖
pip install flask requests

# 2. 启动服务器
node server.js

# 3. 浏览器打开
# http://127.0.0.1:5178
```

本地模式下，`bridge.py` 从你的 IP 直接抓取番茄小说。如果触发验证码，需要等待 IP 冷却。

## 自建代理（推荐，绕过验证码）

### 方式 A：Docker 部署（推荐）

```bash
# 1. 在云服务器上克隆/上传项目文件
#    需要: bridge.py, api_server.py, charset.json, Dockerfile, docker-compose.yml

# 2. 启动
docker compose up -d

# 3. 验证
curl http://localhost:8080/health
curl http://localhost:8080/api/trending
```

### 方式 B：直接部署（Ubuntu/Debian）

```bash
# 在云服务器上
bash deploy.sh

# 会自动安装 python3, flask, 创建 systemd 服务
# 端口默认 8080，可指定: bash deploy.sh 9000
```

### 方式 C：免费方案

- **Railway / Render**：免费额度足够低流量使用
- **阿里云/腾讯云 试用**：新用户通常有 1-3 个月免费轻量服务器

### 连接代理

部署好后，在本地设置环境变量启动：

```bash
# Windows
set REMOTE_API=http://你的服务器IP:8080
node server.js
```

此时所有抓取请求都会走云端服务器，本地 IP 完全不会暴露。

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/search?q=` | GET | 搜索书籍（ixdzs8 + 番茄移动端） |
| `/api/resolve?title=` | GET | 书名 → book_id 解析 |
| `/api/trending` | GET | 番茄首页热榜 |
| `/api/rank/10` | GET | 榜单（10=热榜 11=新书 12=完本 13=口碑） |
| `/api/book/{id}` | GET | 书籍详情 + 章节目录 |
| `/api/book/{id}/chapters` | GET | 章节列表 |
| `/api/book/{id}/download` | POST | 下载（自动选最优源：ixdzs8 ZIP 或 番茄直链） |
| `/api/book/{id}/download-fanqie` | POST | 番茄直链下载（跳过 ixdzs8） |
| `/health` | GET | 健康检查 |
| `/api/stats` | GET | 服务器状态 |

## 文件说明

```
fanqie-desktop-remake/
├── index.html          # 前端 UI
├── app.js              # 前端逻辑（搜索/详情/下载/历史）
├── styles.css          # 暗色主题样式
├── server.js           # Node.js 本地开发服务器
├── bridge.py           # 抓取引擎（搜索/解析/下载/解密）
├── api_server.py       # Flask API 代理服务器（部署到云端）
├── charset.json        # 番茄字体解码表
├── Dockerfile          # Docker 镜像
├── docker-compose.yml  # Docker Compose 部署
├── deploy.sh           # Ubuntu 一键部署脚本
└── README.md
```

## 限流配置

`api_server.py` 内置简易限流：
- 普通接口：60 次/分钟
- 下载接口：10 次/分钟

可根据需要修改 `RATE_MAX_GENERAL` 和 `RATE_MAX_DOWNLOAD`。

## 许可

MIT
