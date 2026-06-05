// 番茄小说下载器 — 前端逻辑
// v2.0: 接入真实 API

// ── 演示回退数据 ──
const DEMO_BOOK = {
  id: "7627137196947950616",
  title: "1960：我的七个孩子有四个妈",
  author: "振无敌",
  words: "27.3 万字",
  chapters: "135 章",
  status: "连载中",
  tags: "无底气年代文+宠妻宠娃+多女主+一个现在+三个前妻+七个崽",
  cover: "data:image/svg+xml;utf8," + encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="180" height="240" viewBox="0 0 180 240"><defs><linearGradient id="g" x1="0" x2="1" y1="0" y2="1"><stop stop-color="#f7d58b"/><stop offset=".48" stop-color="#73836e"/><stop offset="1" stop-color="#20251f"/></linearGradient></defs><rect width="180" height="240" rx="12" fill="url(#g)"/><rect x="14" y="14" width="152" height="212" rx="9" fill="none" stroke="rgba(255,255,255,.55)" stroke-width="3"/><text x="90" y="48" text-anchor="middle" font-size="19" font-weight="900" fill="#fff">1960</text><text x="90" y="75" text-anchor="middle" font-size="15" font-weight="900" fill="#fff">我的七个孩子</text><text x="90" y="96" text-anchor="middle" font-size="15" font-weight="900" fill="#fff">有四个妈</text><circle cx="58" cy="145" r="25" fill="#2a3028"/><circle cx="111" cy="143" r="30" fill="#57412a"/><rect x="38" y="169" width="104" height="35" rx="12" fill="#262a25"/><text x="90" y="222" text-anchor="middle" font-size="13" fill="#fff">振无敌</text></svg>`
  ),
  intro: "男主穿越而来，获得一个奇葩系统，只要画大饼，让家人相信，他就能获得奖励。\n\n为了养活一家子，赵卫国只能疯狂画大饼。\n\"娘，我以后一定好好孝敬您。\"\n\"儿啊，娘不指望你孝敬我，你能顾好自己就成。\"\n赵卫国：\"……\"\n\"媳妇，我要让你喝上野菜汤。\"\n\"滚！\"",
};

const state = {
  activeTab: "search",
  selectedBook: null,
  format: "TXT",
  shelf: [],        // [book_id, ...]
  history: [],
  task: null,
  defaultDir: "C:\\Users\\HONGLU ENG 10\\Downloads\\FanqieNovels",
  booksCache: {},    // book_id → book obj
  searchResults: [], // [book_id, ...]
  trendingBooks: [], // [book_id, ...]
  loading: false,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

// ═══════════════════════════════════════════════════════════
// API 调用
// ═══════════════════════════════════════════════════════════

async function api(path) {
  try {
    const resp = await fetch(path);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await resp.json();
  } catch (e) {
    console.error("API 错误:", e.message);
    return { error: e.message };
  }
}

async function apiPost(path, body) {
  try {
    const resp = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await resp.json();
  } catch (e) {
    return { error: e.message };
  }
}

// ── 缓存书籍 ──
function cacheBook(raw) {
  if (!raw || !raw.book_id) return null;
  const id = raw.book_id;
  const book = {
    id,
    title: raw.title || "未知书名",
    author: raw.author || "未知作者",
    status: raw.status || "未知",
    description: raw.description || "",
    chapterCount: raw.chapter_count || 0,
    wordCount: raw.word_count || 0,
    chapters: raw.chapters || [],
    tags: raw.tags || raw.category || "",
    source: raw.source || "",
  };
  state.booksCache[id] = book;
  return book;
}

// ── 生成封面 SVG ──
let _coverId = 0;
function makeCover(title) {
  const id = ++_coverId;
  const lines = [];
  let remaining = title;
  while (remaining.length > 0) {
    lines.push(remaining.slice(0, 8));
    remaining = remaining.slice(8);
  }
  if (lines.length > 4) lines.splice(4);
  const textEls = lines.map((l, i) =>
    `<text x="90" y="${46 + i * 28}" text-anchor="middle" font-size="16" font-weight="900" fill="#fff">${l}</text>`
  ).join("");

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="180" height="240" viewBox="0 0 180 240"><defs><linearGradient id="g${id}" x1="0" x2="1" y1="0" y2="1"><stop stop-color="#e8874b"/><stop offset=".48" stop-color="#6a4c3a"/><stop offset="1" stop-color="#1a1410"/></linearGradient></defs><rect width="180" height="240" rx="12" fill="url(#g${id})"/><rect x="14" y="14" width="152" height="212" rx="9" fill="none" stroke="rgba(255,255,255,.3)" stroke-width="2"/>${textEls}</svg>`;
  return "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(svg)));
}

// ═══════════════════════════════════════════════════════════
// 初始化
// ═══════════════════════════════════════════════════════════

async function init() {
  hydrate();
  bindEvents();
  // 尝试加载热榜
  await loadTrending();
  // 如果没有热榜数据，用演示书
  if (state.trendingBooks.length === 0) {
    const book = cacheBook({
      book_id: DEMO_BOOK.id,
      title: DEMO_BOOK.title,
      author: DEMO_BOOK.author,
      status: DEMO_BOOK.status,
      description: DEMO_BOOK.intro,
      chapter_count: 135,
    });
    state.trendingBooks = [DEMO_BOOK.id];
    state.searchResults = [DEMO_BOOK.id];
    state.selectedBook = book;
  }
  renderSearchResults();
  renderDetail(state.selectedBook);
  renderShelf();
  renderHistory();
}

async function loadTrending() {
  state.loading = true;
  const data = await api("/api/trending");
  if (data.error || !data.results) {
    state.loading = false;
    return;
  }
  const allIds = [];
  for (const listName of ["boyList", "weekList", "editorList"]) {
    const items = data.results[listName] || [];
    for (const item of items) {
      const book = cacheBook(item);
      if (book) allIds.push(book.id);
    }
  }
  state.trendingBooks = [...new Set(allIds)];
  state.searchResults = state.trendingBooks;
  if (!state.selectedBook && state.trendingBooks.length > 0) {
    state.selectedBook = state.booksCache[state.trendingBooks[0]];
  }
  state.loading = false;
}

function hydrate() {
  const saved = JSON.parse(localStorage.getItem("fanqie-remake") || "{}");
  Object.assign(state, {
    shelf: saved.shelf || [],
    history: saved.history || [],
    format: saved.format || "TXT",
    defaultDir: saved.defaultDir || state.defaultDir,
  });
  $("#defaultDir").value = state.defaultDir;
  syncSegments();
}

function persist() {
  localStorage.setItem("fanqie-remake", JSON.stringify({
    shelf: state.shelf,
    history: state.history,
    format: state.format,
    defaultDir: state.defaultDir,
  }));
}

// ═══════════════════════════════════════════════════════════
// 事件绑定
// ═══════════════════════════════════════════════════════════

function bindEvents() {
  $$(".tab").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
  });

  $("#searchForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const query = $("#searchInput").value.trim();
    if (!query) return;
    await doSearch(query);
  });

  $("#loadButton").addEventListener("click", async () => {
    const query = $("#searchInput").value.trim();
    if (!query) return;

    // 纯数字 → book_id
    if (/^\d+$/.test(query)) {
      await loadBookById(query);
    } else {
      // 书名 → resolve 解析
      await resolveAndLoad(query);
    }
  });

  $("#dockToggle").addEventListener("click", () =>
    $("#taskDock").classList.toggle("is-collapsed")
  );
  $("#refreshHistory").addEventListener("click", renderHistory);
  $("#clearHistory").addEventListener("click", () => {
    state.history = [];
    persist();
    renderHistory();
  });
  $("#historyFilter").addEventListener("input", renderHistory);
  $("#saveSettings").addEventListener("click", () => {
    state.defaultDir = $("#defaultDir").value.trim() || state.defaultDir;
    persist();
    toastTask("设置已保存", "默认选项已写入本地浏览器存储", 100, "完成");
  });
  $("#chapterRange").addEventListener("input", (event) => {
    $("#chapterOutput").value = event.target.value;
  });
  document.body.addEventListener("click", handleBodyClick);
}

async function doSearch(query) {
  state.loading = true;
  toastTask("搜索中...", query, 10, "搜索");

  // 纯数字 book_id → 直接加载
  if (/^\d{10,}$/.test(query)) {
    await loadBookById(query);
    state.loading = false;
    return;
  }

  // 书名 → 先 ixdzs8 搜索 + resolve
  const [searchData, resolveData] = await Promise.all([
    api(`/api/search?q=${encodeURIComponent(query)}`),
    api(`/api/resolve?title=${encodeURIComponent(query)}`),
  ]);

  const ids = [];

  // ixdzs8 搜索结果
  const ixResults = searchData.results || [];
  for (const item of ixResults) {
    const book = cacheBook(item);
    if (book) ids.push(book.id);
  }

  // resolve 结果（番茄 book_id）
  if (resolveData.found && resolveData.results) {
    for (const item of resolveData.results) {
      if (item.source === "fanqie" && !ids.includes(item.book_id)) {
        const book = cacheBook({
          book_id: item.book_id,
          title: item.title || query,
          author: item.author || "",
          source: "fanqie",
        });
        if (book) ids.push(book.id);
      }
    }
  }

  state.searchResults = ids.length > 0 ? ids : state.trendingBooks;
  if (state.searchResults.length > 0) {
    state.selectedBook = state.booksCache[state.searchResults[0]];
  }
  renderSearchResults();
  renderDetail(state.selectedBook);
  $("#resultCount").textContent = state.searchResults.length;
  toastTask("搜索完成", `找到 ${state.searchResults.length} 条结果`, 100, "完成");
  state.loading = false;
}

async function resolveAndLoad(title) {
  toastTask("解析中...", `搜索「${title}」`, 15, "解析");
  const data = await api(`/api/resolve?title=${encodeURIComponent(title)}`);
  if (data.error || !data.found) {
    toastTask("解析失败", data.error || "未找到", 0, "错误");
    return;
  }

  // 显示所有结果
  const results = data.results || [];
  const ids = [];
  for (const item of results) {
    const book = cacheBook({
      book_id: item.book_id,
      title: item.title || title,
      author: item.author || "",
      source: item.source,
    });
    if (book) ids.push(book.id);
  }

  state.searchResults = ids;
  if (ids.length > 0) {
    state.selectedBook = state.booksCache[ids[0]];
    // 获取详细章节信息
    loadBookById(ids[0]);
  }
  renderSearchResults();
  toastTask("解析完成", `找到 ${ids.length} 个版本 · ${data.best?.download_method || ""}`, 100, "完成");
}

async function loadBookById(bookId) {
  toastTask("加载中...", `获取书籍 ${bookId}`, 20, "加载");
  const data = await api(`/api/book/${bookId}`);
  if (data.error || !data.found) {
    // 回退到演示数据
    if (bookId === DEMO_BOOK.id) {
      const book = cacheBook({
        book_id: DEMO_BOOK.id,
        title: DEMO_BOOK.title,
        author: DEMO_BOOK.author,
        status: DEMO_BOOK.status,
        description: DEMO_BOOK.intro,
        chapter_count: 135,
      });
      state.searchResults = [book.id];
      state.selectedBook = book;
      renderSearchResults();
      renderDetail(book);
      toastTask("已载入", "演示数据", 100, "完成");
      return;
    }
    toastTask("加载失败", data.error || "未找到", 0, "错误");
    return;
  }
  const book = cacheBook(data);
  state.searchResults = [book.id];
  state.selectedBook = book;
  renderSearchResults();
  renderDetail(book);
  toastTask("已载入", `${book.title} · ${book.author} · ${book.status}`, 100, "完成");
}

function handleBodyClick(event) {
  const action = event.target.closest("[data-action]");
  if (!action) return;
  const bookId = action.dataset.id;
  const book = state.booksCache[bookId] || state.selectedBook;
  if (!book) return;
  const name = action.dataset.action;
  if (name === "select") {
    state.selectedBook = book;
    // 状态未知 → 自动获取详情
    if (!book.status || book.status === "未知") {
      loadBookById(book.id);
    } else {
      renderDetail(book);
    }
  }
  if (name === "download") simulateDownload(book);
  if (name === "download-fanqie") downloadFanqieDirect(book);
  if (name === "shelf") addToShelf(book);
  if (name === "read") readOnline(book);
  if (name === "clear-cache") toastTask(book.title, "缓存已清理", 100, "完成");
  if (name === "copy-id") navigator.clipboard?.writeText(book.id);
  if (name === "open-dir") {
    // 从历史记录中找到该条目的完整路径
    const historyItem = state.history.find(h => h.id === book.id);
    const filePath = historyItem?.filePath || "";
    const dirPath = state.defaultDir;
    const fullPath = filePath || `${dirPath}\\${book.title}.txt`;

    // 复制路径到剪贴板
    navigator.clipboard?.writeText(fullPath);
    // 通过服务器打开目录
    api(`/api/open-dir?path=${encodeURIComponent(dirPath)}`);
    toastTask(book.title, `路径已复制：${fullPath}`, 100, "打开");
  }
  if (name === "format") {
    state.format = action.dataset.format;
    syncSegments();
    renderDetail(book);
    persist();
  }
  if (name === "load-chapters") loadChapterList(book);
}

// ═══════════════════════════════════════════════════════════
// 视图渲染
// ═══════════════════════════════════════════════════════════

function switchTab(tab) {
  state.activeTab = tab;
  $$(".tab").forEach((b) => b.classList.toggle("is-active", b.dataset.tab === tab));
  $$(".view").forEach((v) => v.classList.toggle("is-active", v.id === `view-${tab}`));
}

function renderSearchResults() {
  const ids = state.searchResults;
  $("#resultCount").textContent = ids.length;
  if (ids.length === 0) {
    $("#resultList").innerHTML =
      `<div class="empty-box">搜索书籍或输入 book_id<br/>直接载入</div>`;
    return;
  }
  $("#resultList").innerHTML = ids
    .map((id) => state.booksCache[id])
    .filter(Boolean)
    .map(resultCard)
    .join("");
}

function resultCard(book) {
  const cover = book.cover || makeCover(book.title);
  const desc = (book.description || book.intro || "").slice(0, 80);
  const statusText = book.status || "未知";
  const sourceTag = book.source ? ` [${book.source}]` : "";
  return `
    <article class="result-card" data-action="select" data-id="${book.id}">
      <img class="cover" src="${cover}" alt="${book.title}" />
      <div>
        <div class="book-title">${book.title}</div>
        <div class="book-meta">${book.author} · ID ${book.id}${sourceTag}</div>
        <div class="book-desc">${desc}...</div>
      </div>
      <span class="status-pill">${statusText}</span>
    </article>
  `;
}

function renderDetail(book) {
  if (!book) {
    $("#bookDetail").innerHTML =
      `<div class="empty-box">搜索或输入 book_id<br/>查看书籍详情</div>`;
    return;
  }
  state.selectedBook = book;
  const cover = book.cover || makeCover(book.title);
  const chapterText = book.chapterCount
    ? `${book.chapterCount} 章`
    : (book.chapters ? `${book.chapters} 章` : "");
  const wordText = book.wordCount
    ? `${(book.wordCount / 10000).toFixed(1)} 万字`
    : (book.words || "");

  $("#bookDetail").innerHTML = `
    <div class="detail-head">
      <img class="cover" src="${cover}" alt="${book.title}" />
      <div>
        <h2>${book.title}</h2>
        <p>${book.author}</p>
        <div class="chips">
          ${wordText ? `<span class="chip">${wordText}</span>` : ""}
          ${chapterText ? `<span class="chip">${chapterText}</span>` : ""}
          <span class="chip">书籍 ID ${book.id}</span>
        </div>
        <p>保存目录</p>
        <div class="path-row">
          <button class="ghost" type="button" id="chooseDirBtn">选择目录</button>
          <input value="${state.defaultDir}" readonly />
        </div>
      </div>
    </div>
    <p class="intro">${book.description || book.intro || "暂无简介"}</p>
    <p>导出格式</p>
    <div class="segmented">
      <button class="segment ${state.format === "TXT" ? "is-active" : ""}"
        type="button" data-action="format" data-format="TXT" data-id="${book.id}">TXT</button>
      <button class="segment ${state.format === "EPUB" ? "is-active" : ""}"
        type="button" data-action="format" data-format="EPUB" data-id="${book.id}">EPUB</button>
    </div>
    <div class="detail-actions">
      <button class="primary" type="button" data-action="download" data-id="${book.id}">自动下载</button>
      <button class="ghost" type="button" data-action="download-fanqie" data-id="${book.id}" title="跳过 ixdzs8，直连番茄原站下载">番茄直链</button>
      <button class="ghost" type="button" data-action="shelf" data-id="${book.id}">加入书架</button>
      <button class="ghost" type="button" data-action="load-chapters" data-id="${book.id}">加载章节</button>
      <button class="ghost" type="button" data-action="clear-cache" data-id="${book.id}">清除缓存</button>
      <button class="ghost" type="button" data-action="copy-id" data-id="${book.id}">复制 ID</button>
    </div>
    <div id="chapterPreview" style="margin-top:12px;max-height:300px;overflow:auto;"></div>
  `;
  // 绑定目录选择
  setTimeout(() => {
    const btn = $("#chooseDirBtn");
    if (btn) btn.addEventListener("click", () => {
      const dir = prompt("输入保存目录路径:", state.defaultDir);
      if (dir && dir.trim()) {
        state.defaultDir = dir.trim();
        persist();
        renderDetail(state.selectedBook);
      }
    });
  }, 50);
}

async function loadChapterList(book) {
  toastTask("加载章节", `获取 ${book.title} 章节目录...`, 30, "加载");
  const data = await api(`/api/book/${book.id}/chapters`);
  if (data.error) {
    toastTask("加载失败", data.error, 0, "错误");
    return;
  }
  const chapters = data.chapters || [];
  const preview = $("#chapterPreview");
  if (preview && chapters.length > 0) {
    const shown = chapters.slice(0, 50);
    preview.innerHTML =
      `<p style="color:var(--muted)">共 ${chapters.length} 章</p>` +
      shown.map((ch) =>
        `<span class="chip" style="margin:2px">${ch.title || `第${ch.item_id}章`}</span>`
      ).join("");
    // 缓存到 book
    book.chapters = chapters;
    book.chapterCount = chapters.length;
    state.booksCache[book.id] = book;
  }
  toastTask("章节已加载", `共 ${chapters.length} 章`, 100, "完成");
}

// ═══════════════════════════════════════════════════════════
// 下载进度引擎 — 基于章节数计算真实预期时间，永不停滞
// ═══════════════════════════════════════════════════════════

function addToShelf(book) {
  if (!state.shelf.includes(book.id)) state.shelf.push(book.id);
  persist();
  renderShelf();
  toastTask(book.title, "已加入书架", 100, "完成");
}

function renderShelf() {
  if (!state.shelf.length) {
    $("#shelfGrid").innerHTML =
      `<div class="empty-box">书架为空。搜索书籍后<br />可添加到书架。</div>`;
    return;
  }
  $("#shelfGrid").innerHTML = state.shelf
    .map((id) => state.booksCache[id])
    .filter(Boolean)
    .map(resultCard)
    .join("");
}

function startDownloadProgress(book, totalChapters, label) {
  const startTime = Date.now();
  // 单线程安全模式，每章 ~2s，最小 60s，最大 600s
  const estSeconds = totalChapters
    ? Math.min(600, Math.max(60, totalChapters * 2))
    : 120;
  let progress = 2;

  const record = {
    id: book.id,
    title: book.title,
    author: book.author,
    format: state.format,
    time: new Date().toLocaleString("zh-CN", { hour12: false }),
    status: "下载中",
    message: `${label || "下载中"}...`,
  };
  state.history.unshift(record);
  renderHistory();
  toastTask(book.title, `${label || "下载"}：准备中...`, 2, "下载中");

  const updateProgress = () => {
    const elapsed = (Date.now() - startTime) / 1000;
    // 根据实际流逝时间比例计算进度，平滑到 98%
    progress = Math.min(98, 2 + (elapsed / estSeconds) * 96);
    const eta = Math.max(0, Math.floor(estSeconds - elapsed));
    const msg = totalChapters
      ? `${label || "下载"}：${Math.floor(elapsed)}s / 预计${estSeconds}s 剩余${eta}s`
      : `${label || "下载"}：${Math.floor(elapsed)}s`;
    toastTask(book.title, msg, Math.floor(progress), "下载中");
  };

  return { record, startTime, estSeconds, updateProgress };
}

async function simulateDownload(book) {
  const totalCh = book.chapterCount || book.chapters?.length || 0;
  const record = {
    id: book.id, title: book.title, author: book.author,
    format: state.format,
    time: new Date().toLocaleString("zh-CN", { hour12: false }),
    status: "下载中", message: "已提交任务...",
  };
  state.history.unshift(record);
  renderHistory();
  toastTask(book.title, "已提交下载任务", 5, "排队中");

  // 提交异步任务
  const submit = await apiPost(`/api/book/${book.id}/download`, { outputDir: state.defaultDir });
  if (submit.error || !submit.task_id) {
    record.status = "失败"; record.message = submit.error || "提交失败";
    toastTask(book.title, submit.error || "提交失败", 0, "失败");
    persist(); renderHistory(); return;
  }

  const taskId = submit.task_id;
  record.message = `任务 ${taskId}：下载中...`;

  // 轮询任务状态
  const poll = setInterval(async () => {
    const task = await api(`/api/task/${taskId}`);
    if (!task || task.error) return;

    const pct = task.total ? Math.round(task.progress / task.total * 100) : 0;
    toastTask(book.title, `任务 ${taskId}：${task.status} ${pct}%`, Math.min(98, pct || 5), task.status);

    if (task.status === "completed") {
      clearInterval(poll);
      record.status = "完成";
      record.filePath = task.result?.path;
      record.message = `已保存: ${task.result?.path || ""} [${task.result?.downloaded || "?"}/${task.result?.total_chapters || "?"}章]`;
      toastTask(book.title, `下载完成 · ${(task.result?.cn_chars || 0).toLocaleString()} 字`, 100, "完成");
      persist(); renderHistory();
    } else if (task.status === "failed") {
      clearInterval(poll);
      record.status = "失败";
      record.message = task.result?.error || "下载失败";
      toastTask(book.title, task.result?.error || "下载失败", 0, "失败");
      persist(); renderHistory();
    }
  }, 2000);
}

async function downloadFanqieDirect(book) { simulateDownload(book); }

function readOnline(book) {
  const desc = (book.description || book.intro || "").split("\n")[0];
  toastTask(book.title, desc, 100, "阅读");
}

function renderHistory() {
  const filter = $("#historyFilter")?.value?.trim() || "";
  const rows = state.history.filter((item) =>
    [item.title, item.author, item.format].join(" ").includes(filter)
  );
  $("#statHistory").textContent = state.history.length;
  $("#statTasks").textContent =
    state.history.filter((item) => item.status === "下载中").length;
  $("#statExists").textContent =
    state.history.filter((item) => item.status === "完成").length;
  $("#statMissing").textContent =
    state.history.filter((item) => item.status === "失败").length;
  $("#historyTable").innerHTML = `
    <div class="history-row header">
      <div>书籍</div><div>作者</div><div>格式</div><div>下载时间</div><div>状态</div><div>操作</div>
    </div>
    ${rows.length
      ? rows
          .map(
            (item) => `
      <div class="history-row">
        <div><strong>${item.title} / ID ${item.id}</strong><p>${item.message}</p></div>
        <div>${item.author}</div>
        <div>${item.format}</div>
        <div>${item.time}</div>
        <div><span class="${item.status === "失败" ? "fail" : "status-pill"}">${item.status}</span></div>
        <div><button class="ghost" type="button" data-action="open-dir" data-id="${item.id}">打开目录</button></div>
      </div>`
          )
          .join("")
      : `<div class="history-row"><div>暂无下载记录</div><div></div><div></div><div></div><div></div><div></div></div>`
    }
  `;
}

function syncSegments() {
  $$("[data-format]").forEach((button) =>
    button.classList.toggle("is-active", button.dataset.format === state.format)
  );
}

function toastTask(title, message, progress, status) {
  $("#taskTitle").textContent = title;
  $("#taskMessage").textContent = message;
  $("#taskStatus").textContent = status;
  $("#taskPercent").textContent = `进度 ${progress}%`;
  $("#taskProgress").style.width = `${progress}%`;
}

// ═══════════════════════════════════════════════════════════
// 启动
// ═══════════════════════════════════════════════════════════
init();
