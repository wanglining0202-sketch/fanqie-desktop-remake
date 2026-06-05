const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const { exec } = require("node:child_process");
const https = require("node:https");

const root = __dirname;
const port = Number(process.env.PORT || 5178);
const python = process.env.PYTHON
  || "J:/Hermes Agent/venv/Scripts/python.exe"
  || "python";
const bridge = path.join(root, "bridge.py");

// 远程 API 代理模式：设置 REMOTE_API=http://your-server:8080 即可
const REMOTE_API = process.env.REMOTE_API || "";

const types = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".json": "application/json; charset=utf-8",
};

function callBridge(cmd, timeoutSec, ...args) {
  // 远程 API 模式：转发到云端服务器
  if (REMOTE_API) {
    return remoteProxy(cmd, args);
  }

  return new Promise((resolve) => {
    const cmdline = [bridge, cmd, ...args].map((s) => `"${s}"`).join(" ");
    const fullCmd = `"${python}" ${cmdline}`;
    exec(fullCmd, {
      timeout: (timeoutSec || 30) * 1000,
      maxBuffer: 50 * 1024 * 1024,
      env: { ...process.env, PYTHONIOENCODING: "utf-8" },
    }, (error, stdout) => {
      if (error && !stdout) {
        return resolve({ error: error.killed ? `请求超时 (${timeoutSec}s)` : `桥接调用失败: ${error.message}` });
      }
      try { resolve(JSON.parse(stdout)); }
      catch { resolve({ error: "桥接返回解析失败", raw: stdout.slice(0, 500) }); }
    });
  });
}

// 远程 API 代理：将请求转发到云端服务器
function remoteProxy(cmd, args) {
  return new Promise((resolve) => {
    const route = buildRemoteRoute(cmd, args);
    if (!route) return resolve({ error: `不支持的远程命令: ${cmd}` });

    const client = REMOTE_API.startsWith("https") ? https : http;
    const url = new URL(route.path, REMOTE_API);

    const options = {
      method: route.method || "GET",
      timeout: route.timeout || 30000,
      headers: { "Content-Type": "application/json" },
    };

    const req = client.request(url, options, (res) => {
      let body = "";
      res.on("data", (c) => body += c);
      res.on("end", () => {
        try { resolve(JSON.parse(body)); }
        catch { resolve({ error: "远程响应解析失败" }); }
      });
    });
    req.on("error", (e) => resolve({ error: `远程 API 不可达: ${e.message}` }));
    req.on("timeout", () => { req.destroy(); resolve({ error: "远程 API 超时" }); });

    if (route.body) {
      req.write(JSON.stringify(route.body));
    }
    req.end();
  });
}

function buildRemoteRoute(cmd, args) {
  const m = {
    search:     () => ({ method: "GET",  path: `/api/search?q=${encodeURIComponent(args[0] || "")}` }),
    resolve:    () => ({ method: "GET",  path: `/api/resolve?title=${encodeURIComponent(args[0] || "")}` }),
    info:       () => ({ method: "GET",  path: `/api/book/${args[0] || ""}` }),
    chapters:   () => ({ method: "GET",  path: `/api/book/${args[0] || ""}/chapters` }),
    trending:   () => ({ method: "GET",  path: "/api/trending" }),
    rank:       () => ({ method: "GET",  path: `/api/rank/${args[0] || "10"}` }),
    download:   () => ({ method: "POST", path: `/api/book/${args[0] || ""}/download`,  body: { outputDir: args[1] || "" }, timeout: 600000 }),
    download_fanqie: () => ({ method: "POST", path: `/api/book/${args[0] || ""}/download-fanqie`, body: { outputDir: args[1] || "" }, timeout: 600000 }),
  };
  return m[cmd] ? m[cmd]() : null;
}

function jsonReply(res, data, status = 200) {
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(data, null, 2));
}

function routeAPI(req, res) {
  const url = new URL(req.url, `http://127.0.0.1:${port}`);
  const p = url.pathname;
  const m = req.method;

  if (p === "/api/search" && m === "GET") {
    const q = url.searchParams.get("q") || "";
    if (!q.trim()) return jsonReply(res, { error: "缺少搜索词" }, 400);
    return callBridge("search", 30, q).then((r) => jsonReply(res, r));
  }

  if (p === "/api/resolve" && m === "GET") {
    const t = url.searchParams.get("title") || "";
    if (!t.trim()) return jsonReply(res, { error: "缺少书名" }, 400);
    return callBridge("resolve", 30, t).then((r) => jsonReply(res, r));
  }

  if (p === "/api/trending" && m === "GET")
    return callBridge("trending", 30).then((r) => jsonReply(res, r));

  const bookMatch = p.match(/^\/api\/book\/(\d+)$/);
  if (bookMatch && m === "GET")
    return callBridge("info", 30, bookMatch[1]).then((r) => jsonReply(res, r));

  const chMatch = p.match(/^\/api\/book\/(\d+)\/chapters$/);
  if (chMatch && m === "GET")
    return callBridge("chapters", 30, chMatch[1]).then((r) => jsonReply(res, r));

  const dlMatch = p.match(/^\/api\/book\/(.+)\/download$/);
  if (dlMatch && m === "POST") {
    let body = "";
    req.on("data", (c) => body += c);
    return req.on("end", () => {
      let dir = ""; try { dir = JSON.parse(body).outputDir || ""; } catch {}
      const id = decodeURIComponent(dlMatch[1]);
      const args = dir ? [id, dir] : [id];
      return callBridge("download", 600, ...args).then((r) => jsonReply(res, r));
    });
  }

  const dlFqMatch = p.match(/^\/api\/book\/(.+)\/download-fanqie$/);
  if (dlFqMatch && m === "POST") {
    let body = "";
    req.on("data", (c) => body += c);
    return req.on("end", () => {
      let dir = ""; try { dir = JSON.parse(body).outputDir || ""; } catch {}
      const id = decodeURIComponent(dlFqMatch[1]);
      const args = dir ? [id, dir] : [id];
      return callBridge("download_fanqie", 600, ...args).then((r) => jsonReply(res, r));
    });
  }

  const rankMatch = p.match(/^\/api\/rank\/(\d+)$/);
  if (rankMatch && m === "GET")
    return callBridge("rank", 30, rankMatch[1]).then((r) => jsonReply(res, r));

  // GET /api/open-dir?path=xxx
  if (p === "/api/open-dir" && m === "GET") {
    const dir = url.searchParams.get("path") || "";
    if (dir) {
      const { exec } = require("node:child_process");
      exec(`explorer "${dir.replace(/\//g, "\\")}"`, () => {});
    }
    return jsonReply(res, { ok: true });
  }

  return jsonReply(res, { error: "API 不存在" }, 404);
}

function serveStatic(req, res) {
  const up = decodeURIComponent(new URL(req.url, `http://127.0.0.1:${port}`).pathname);
  const requested = up === "/" ? "/index.html" : up;
  if (requested.startsWith("/api/")) return routeAPI(req, res);
  const file = path.normalize(path.join(root, requested));
  if (!file.startsWith(root)) { res.writeHead(403); return res.end("Forbidden"); }
  fs.readFile(file, (e, d) => {
    if (e) { res.writeHead(404); return res.end("Not found"); }
    res.writeHead(200, { "Content-Type": types[path.extname(file)] || "application/octet-stream" });
    res.end(d);
  });
}

http.createServer(serveStatic).listen(port, "127.0.0.1", () => {
  console.log(`番茄小说下载器 running at http://127.0.0.1:${port}`);
  console.log(`  Python: ${python}\n  Bridge: ${bridge}`);
});
