#!/usr/bin/env python3
"""fanqie-desktop-remake 后端桥接层

作为 Node.js server.js 和抓取工具之间的 JSON 桥接。
接受 CLI 命令，输出 JSON 到 stdout。

用法:
  python bridge.py search <keyword>
  python bridge.py info <book_id>
  python bridge.py trending
  python bridge.py rank <category_id>
  python bridge.py download <book_id> [output_dir]
  python bridge.py download_fanqie <book_id> [output_dir]
  python bridge.py chapters <book_id>
"""

import json
import sys
import os
import re
import time
import random
import pathlib
import io
import zipfile
import concurrent.futures
from urllib.parse import quote

# 导入 番茄下载器 FanqieClient
FQ_TOOLS = pathlib.Path("J:/小说模板/小说工程模板/tools")
if str(FQ_TOOLS) not in sys.path:
    sys.path.insert(0, str(FQ_TOOLS))

try:
    from fanqie_downloader import FanqieClient
    FQ_CLIENT_AVAILABLE = True
except ImportError as e:
    FQ_CLIENT_AVAILABLE = False
    FQ_IMPORT_ERROR = str(e)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

try:
    import requests
except ImportError:
    print(json.dumps({"error": "请安装 requests: pip install requests"}))
    sys.exit(1)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
BASE_FQ = "https://fanqienovel.com"
BASE_IX = "https://ixdzs8.com"
BASE_DOWN = "https://down7.ixdzs8.com"

# ── 移动端 API（来源：ying-ck/fanqienovel-downloader，绕过 PC 端验证码）──
FQ_MOBILE_API = "https://api5-normal-lf.fqnovel.com"
FQ_READER_API = f"{BASE_FQ}/api/reader/full"  # 备选章节 API
CHARSET_URL = "https://raw.githubusercontent.com/ying-ck/fanqienovel-downloader/main/src/charset.json"

session = requests.Session()
session.headers.update({"User-Agent": UA})

# ── 字体解码表 ──
_charset = None  # ying-ck charset.json (两套模式)
_pua_map = None  # 362 字体映射表

def _load_charset() -> list:
    """加载 ying-ck 项目的 charset.json 用于内容解码。"""
    global _charset
    if _charset is not None:
        return _charset
    # 优先本地
    local = pathlib.Path(__file__).parent / "charset.json"
    if local.exists():
        with open(local, encoding="utf-8") as f:
            _charset = json.load(f)
            return _charset
    # 从 GitHub 下载
    try:
        resp = requests.get(CHARSET_URL, timeout=10)
        _charset = resp.json()
        with open(local, "w", encoding="utf-8") as f:
            json.dump(_charset, f)
    except Exception:
        _charset = [[], []]
    return _charset


def _gen_cookie() -> str:
    """生成随机 novel_web_id cookie（ying-ck 项目方法）。"""
    bas = 1000000000000000000
    return f"novel_web_id={random.randint(bas * 6, bas * 9)}"


def _decode_charset(content: str) -> str:
    """使用 ying-ck charset 解码内容（两套 CODE 范围）。"""
    charset = _load_charset()
    CODE = [[58344, 58715], [58345, 58716]]
    for mode in range(2):
        if not charset[mode]:
            continue
        result = ""
        ok = True
        for char in content:
            uni = ord(char)
            if CODE[mode][0] <= uni <= CODE[mode][1]:
                bias = uni - CODE[mode][0]
                if 0 <= bias < len(charset[mode]) and charset[mode][bias] != "?":
                    result += charset[mode][bias]
                else:
                    ok = False
                    break
            else:
                result += char
        if ok and any("\u4e00" <= c <= "\u9fff" for c in result[:200]):
            return result
    return content  # 解码失败，返回原文


# ═══════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════

def extract_initial_state(html: str) -> dict | None:
    """从 HTML 提取 window.__INITIAL_STATE__ JSON。"""
    pos = html.find("window.__INITIAL_STATE__=")
    if pos < 0:
        return None
    start = pos + len("window.__INITIAL_STATE__=")
    depth, end = 0, start
    in_string, esc = False, False
    for i in range(start, len(html)):
        ch = html[i]
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"' and not esc:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    try:
        return json.loads(html[start:end])
    except json.JSONDecodeError:
        return None


def safe_get(url: str, retries: int = 2) -> requests.Response:
    """带重试的 GET 请求。"""
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
            return resp
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def ixdzs8_search(keyword: str, limit: int = 20) -> list[dict]:
    """在 ixdzs8 搜索书籍。"""
    try:
        url = f"{BASE_IX}/bsearch?q={quote(keyword)}"
        resp = safe_get(url)
        html = resp.text

        results = []
        # 结果格式: <li class="burl" data-url="/read/{book_id}/">
        #   <h3 class="bname"><a>title</a></h3>
        #   <span class="bauthor"><a>author</a></span>
        book_pattern = re.compile(
            r'<li\s+class="burl"\s+data-url="/read/(\d+)/">'
            r'(.*?)</li>',
            re.DOTALL,
        )
        title_pattern = re.compile(r'<h3\s+class="bname">\s*<a[^>]*>(.*?)</a>', re.DOTALL)
        author_pattern = re.compile(r'<span\s+class="bauthor">\s*<a[^>]*>(.*?)</a>', re.DOTALL)
        desc_pattern = re.compile(r'<p\s+class="l-p2">(.*?)</p>', re.DOTALL)

        for m in book_pattern.finditer(html):
            book_id = m.group(1)
            block = m.group(2)

            tm = title_pattern.search(block)
            title = re.sub(r"<[^>]+>", "", tm.group(1)).strip() if tm else ""

            am = author_pattern.search(block)
            author = re.sub(r"<[^>]+>", "", am.group(1)).strip() if am else ""

            if title and book_id:
                results.append({
                    "book_id": book_id,
                    "title": title,
                    "author": author,
                    "source": "ixdzs8",
                })

            if len(results) >= limit:
                break

        # 如果 ixdzs8 没搜到，尝试直接搜 fanqienovel.com（可能被屏蔽但值得一试）
        if not results:
            try:
                fq_url = f"{BASE_FQ}/search?keyword={quote(keyword)}"
                resp2 = safe_get(fq_url)
                state = extract_initial_state(resp2.text)
                if state:
                    book_list = state.get("search", {}).get("searchBookList", [])
                    if isinstance(book_list, str):
                        book_list = json.loads(book_list)
                    for item in (book_list if isinstance(book_list, list) else [])[:limit]:
                        if isinstance(item, dict):
                            results.append({
                                "book_id": str(item.get("bookId", "")),
                                "title": item.get("bookName", ""),
                                "author": item.get("author", ""),
                                "source": "fanqie",
                            })
            except Exception:
                pass

        return results
    except Exception as e:
        return [{"error": str(e)}]


# ═══════════════════════════════════════════════════════════
# 命令处理
# ═══════════════════════════════════════════════════════════

def fanqie_mobile_search(keyword: str, limit: int = 20) -> list[dict]:
    """番茄移动端 API 搜索（api5-normal-lf.fqnovel.com）。
    
    模拟手机设备参数，绕过 PC 端搜索封锁。
    来源：ying-ck/fanqienovel-downloader
    """
    try:
        url = f"{FQ_MOBILE_API}/reading/bookapi/search/page/v/"
        params = {
            "query": keyword,
            "aid": "1967",
            "channel": "0",
            "os_version": "0",
            "device_type": "0",
            "device_platform": "0",
            "iid": "466614321180296",
            "version_code": "999",
        }
        resp = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 0 or not data.get("data"):
            return []

        results = []
        for item in data["data"][:limit]:
            if isinstance(item, dict):
                results.append({
                    "book_id": str(item.get("book_id", item.get("bookId", ""))),
                    "title": item.get("book_name", item.get("bookName", item.get("title", ""))),
                    "author": item.get("author", ""),
                    "description": (item.get("abstract", "") or "")[:200],
                    "source": "fanqie_mobile",
                })
        return results
    except Exception as e:
        return [{"error": f"移动端搜索失败: {str(e)}"}]


def cmd_search(keyword: str) -> dict:
    """搜索书籍（ixdzs8 + 番茄移动端 API 双通道）。"""
    results = ixdzs8_search(keyword)
    # 同时尝试番茄移动端搜索
    mobile_results = fanqie_mobile_search(keyword)
    seen_ids = {r.get("book_id") for r in results if "error" not in r}
    for r in mobile_results:
        if "error" not in r and r.get("book_id") not in seen_ids:
            results.append(r)
    return {"results": results, "count": len(results)}


def cmd_info(book_id: str) -> dict:
    """获取书籍详情（从 fanqienovel.com 页面）。"""
    # 1. 尝试 fanqienovel.com
    try:
        url = f"{BASE_FQ}/page/{book_id}"
        resp = safe_get(url)
        state = extract_initial_state(resp.text)
        if state:
            page = state.get("page", {})
            # 提取章节 itemId 列表
            chapters = []
            chapter_matches = re.findall(
                r'"itemId":"([^"]+)","needPay":(\d+),"title":"([^"]*)"',
                resp.text,
            )
            for item_id, need_pay, title in chapter_matches:
                chapters.append({
                    "item_id": item_id,
                    "title": title,
                    "need_pay": need_pay == "1",
                })

            return {
                "found": True,
                "source": "fanqie",
                "book_id": book_id,
                "title": page.get("bookName", ""),
                "author": page.get("author", ""),
                "status": "完结" if page.get("status") == 1 else "连载中",
                "description": (page.get("abstract", "") or "")[:500],
                "chapter_count": page.get("chapterCount", len(chapters)),
                "word_count": page.get("wordCount", 0),
                "chapters": chapters,
                "tags": "",
            }
    except Exception:
        pass

    # 1b. HTML 没章节 → 目录 API（zhongbai2333 方案）
    if not chapters:
        try:
            dir_url = f"{BASE_FQ}/api/reader/directory/detail?bookId={book_id}"
            resp = requests.get(dir_url, headers={"User-Agent": UA}, timeout=15)
            data = resp.json()
            # 支持 chapterList / chapterListWithVolume / data.chapterList 等多种格式
            chapter_list = None
            for key in ["chapterList", "data"]:
                val = data.get(key, {})
                if isinstance(val, dict):
                    for sub in ["chapterList", "chapters", "items", "list"]:
                        if sub in val:
                            chapter_list = val[sub]
                            break
                elif isinstance(val, list):
                    chapter_list = val
                if chapter_list:
                    break
            # 展平 chapterListWithVolume
            if not chapter_list and "chapterListWithVolume" in data:
                chapter_list = []
                for vol in data["chapterListWithVolume"]:
                    chapter_list.extend(vol if isinstance(vol, list) else vol.get("chapterList", vol.get("chapters", [])))
            
            if isinstance(chapter_list, list):
                for ch in chapter_list:
                    if isinstance(ch, dict):
                        chapters.append({
                            "item_id": str(ch.get("itemId", ch.get("item_id", ch.get("id", "")))),
                            "title": ch.get("title", ""),
                            "need_pay": False,
                        })
        except Exception:
            pass

    # 2. 尝试 ixdzs8 信息页
    try:
        url = f"{BASE_IX}/read/{book_id}/"
        resp = safe_get(url)
        html = resp.text
        title_m = re.search(r"<h1[^>]*>(.*?)</h1>", html)
        author_m = re.search(r'作者[：:]\s*(.*?)[<\n]', html)
        desc_m = re.search(r'<div[^>]*class="[^"]*intro[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)

        # 提取章节链接
        chapter_links = re.findall(r'href="/read/' + re.escape(book_id) + r'/p(\d+)\.html">([^<]+)</a>', html)

        chapters = [
            {"item_id": f"p{num}", "title": title.strip(), "need_pay": False}
            for num, title in chapter_links
        ]

        return {
            "found": True,
            "source": "ixdzs8",
            "book_id": book_id,
            "title": re.sub(r"<[^>]+>", "", title_m.group(1)).strip() if title_m else "",
            "author": author_m.group(1).strip() if author_m else "",
            "status": "未知",
            "description": re.sub(r"<[^>]+>", "", desc_m.group(1)).strip()[:500] if desc_m else "",
            "chapter_count": len(chapters),
            "word_count": 0,
            "chapters": chapters,
            "tags": "",
        }
    except Exception:
        pass

    return {"found": False, "error": f"未找到书籍: {book_id}"}


def cmd_trending() -> dict:
    """获取番茄首页热榜。"""
    try:
        url = f"{BASE_FQ}/"
        resp = safe_get(url)
        state = extract_initial_state(resp.text)
        if not state:
            return {"error": "无法解析首页数据"}

        home = state.get("home", {})
        results = {}

        for list_name in ["boyList", "weekList", "editorList"]:
            lst = home.get(list_name, [])
            if isinstance(lst, list) and lst and isinstance(lst[0], str):
                try:
                    lst = json.loads(lst[0])
                except json.JSONDecodeError:
                    lst = []

            books = []
            for item in (lst if isinstance(lst, list) else []):
                if isinstance(item, dict):
                    books.append({
                        "book_id": str(item.get("bookId", item.get("book_id", ""))),
                        "title": item.get("bookName") or item.get("book_name") or item.get("title", ""),
                        "author": item.get("author", ""),
                        "description": (item.get("abstract", "") or "")[:200],
                    })
            if books:
                results[list_name] = books

        return {"results": results}
    except Exception as e:
        return {"error": str(e)}


def cmd_rank(category_id: str = "10", page: int = 1) -> dict:
    """获取榜单。category_id: 10=热榜 11=新书 12=完本 13=口碑"""
    try:
        url = f"{BASE_FQ}/rank/{category_id}?page={page}"
        resp = safe_get(url)
        state = extract_initial_state(resp.text)
        if not state:
            return {"error": "无法解析榜单数据"}

        rank = state.get("rank", {})
        book_list = rank.get("book_list", [])
        if isinstance(book_list, str):
            try:
                book_list = json.loads(book_list)
            except json.JSONDecodeError:
                book_list = []

        books = []
        for item in book_list:
            if isinstance(item, dict):
                books.append({
                    "book_id": str(item.get("bookId", item.get("book_id", ""))),
                    "title": item.get("bookName") or item.get("book_name") or item.get("title", ""),
                    "author": item.get("author", ""),
                    "category": item.get("categoryName", ""),
                    "description": (item.get("abstract", "") or "")[:200],
                })

        return {"results": books, "count": len(books), "category_id": category_id}
    except Exception as e:
        return {"error": str(e)}


def cmd_download(book_id: str, output_dir: str = None) -> dict:
    """三源下载：ixdzs8 ZIP 优先 → 番茄移动端 → 番茄 web 直链回退。"""
    if output_dir is None:
        output_dir = str(pathlib.Path.home() / "Downloads" / "FanqieNovels")
    os.makedirs(output_dir, exist_ok=True)

    # 0. 非数字 → 解析书名
    if not re.match(r"^\d+$", book_id):
        resolved = cmd_resolve(book_id)
        if not resolved.get("found"):
            return {"success": False, "error": resolved.get("error", f"无法解析「{book_id}」")}
        best = resolved.get("best", {})
        book_id = best.get("book_id", book_id)
        if best.get("download_method") == "ixdzs8_zip":
            result = _try_download_zip(book_id, best.get("title", book_id), output_dir)
            if result["success"]:
                return result
        return cmd_download_fanqie(book_id, output_dir)

    # 1. 获取书名 → ixdzs8 交叉搜索 → 优先 ZIP（秒级，不触发风控）
    info = cmd_info(book_id)
    title = info.get("title", "")
    author = info.get("author", "")

    if title:
        # 搜索 ixdzs8，找同名书
        ix_results = ixdzs8_search(f"{title} {author}".strip(), limit=5)
        for r in ix_results:
            if "error" in r:
                continue
            r_title = re.sub(r"[（）()\s]", "", r.get("title", ""))
            t_clean = re.sub(r"[（）()\s]", "", title)
            # 标题匹配
            if r_title == t_clean or t_clean in r_title or r_title in t_clean:
                print(f"[bridge] ixdzs8 匹配: {r['title']} (id={r['book_id']})", file=sys.stderr)
                result = _try_download_zip(r["book_id"], title, output_dir)
                if result["success"]:
                    return result
                break  # 匹配到了但ZIP失败，不再试其他

    # 2. ixdzs8 没有 → 番茄直链
    return cmd_download_fanqie(book_id, output_dir)


# ── 番茄原站下载（独立请求 + PUA 字体解密） ──

# 字体映射表（延迟加载）
_font_map = None

def _load_font_map() -> dict:
    global _font_map
    if _font_map is not None:
        return _font_map
    mapfile = pathlib.Path("J:/小说模板/小说工程模板/state/fanqie_font_map.json")
    if mapfile.exists():
        with open(mapfile, encoding="utf-8") as f:
            data = json.load(f)
        _font_map = {chr(int(k, 16)): v for k, v in data["map"].items()}
    else:
        _font_map = {}
    return _font_map


def _fetch_chapter_direct(book_id: str, item_id: str) -> str:
    """获取章节。INIT_STATE+PUA → XPath+charset → 403退避重试。"""
    cookie = _gen_cookie()
    headers = {"User-Agent": UA, "Cookie": cookie, "Referer": f"{BASE_FQ}/page/{book_id}"}

    for attempt in range(3):
        # ① INIT_STATE + PUA
        try:
            resp = requests.get(f"{BASE_FQ}/reader/{book_id}?itemId={item_id}", headers=headers, timeout=15)
            html = resp.text
            
            # 403/验证码 → 退避重试
            if len(html) < 10000 and ("sec_sdk" in html or resp.status_code == 403):
                time.sleep(2 ** attempt)  # 1s, 2s, 4s
                continue
            
            pos = html.find("window.__INITIAL_STATE__=")
            if pos >= 0:
                start = pos + len("window.__INITIAL_STATE__=")
                decoder = json.JSONDecoder()
                state, _ = decoder.raw_decode(html[start:])
                content = state.get("reader", {}).get("chapterData", {}).get("content", "")
                if content and len(content) > 200:
                    pua_map = _load_font_map()
                    if pua_map:
                        decoded = "".join(pua_map.get(c, c) for c in content)
                    else:
                        decoded = _decode_charset(content)
                    decoded = re.sub(r"<br\s*/?>", "\n", decoded, flags=re.I)
                    decoded = re.sub(r"<[^>]+>", "", decoded)
                    if sum(1 for c in decoded if "\u4e00" <= c <= "\u9fff") >= 200:
                        return decoded.strip()
        except Exception:
            pass
        
        # ② XPath + charset 回退
        try:
            resp = requests.get(f"{BASE_FQ}/reader/{item_id}", headers=headers, timeout=15)
            p_matches = re.findall(r'<p[^>]*>([^<]+)</p>', resp.text)
            if p_matches and len(p_matches) > 5:
                content = "\n".join(p_matches)
                decoded = _decode_charset(content)
                if sum(1 for c in (decoded or "") if "\u4e00" <= c <= "\u9fff") >= 200:
                    return decoded.strip()
        except Exception:
            pass
        
        time.sleep(0.5)

    return ""


def cmd_download_fanqie(book_id: str, output_dir: str = None) -> dict:
    """番茄原站直链下载（独立请求 + PUA 解密，362/362 字体映射表）。

    下载策略:
      ① 每次请求新建 Session → 避免 cookie 累积触发验证码
      ② PUA 字体解密（362/362 映射表）
      ③ 1.5s 间隔限速
    """
    if output_dir is None:
        output_dir = str(pathlib.Path.home() / "Downloads" / "FanqieNovels")

    os.makedirs(output_dir, exist_ok=True)

    # 1. 获取书籍信息（用 FanqieClient 读 /page/ 页面）
    if not FQ_CLIENT_AVAILABLE:
        info = cmd_info(book_id)
        if not info.get("found"):
            return {"success": False, "error": f"未找到书籍: {book_id}"}
        title = info.get("title", book_id)
        author = info.get("author", "")
        chapters = info.get("chapters", [])
    else:
        client = FanqieClient(delay=1.0)
        try:
            book = client.get_book_info(book_id)
        except Exception as e:
            return {"success": False, "error": f"获取书籍信息失败: {str(e)}"}
        title = book.get("title", book_id)
        author = book.get("author", "")
        chapters = book.get("chapters", [])

    if not chapters:
        return {"success": False, "error": "无章节数据"}

    safe_title = re.sub(r'[\\/:*?"<>|]', "_", title)
    output_path = os.path.join(output_dir, f"{safe_title}.txt")

    # 2. 下载章节（ying-ck 方案：16线程，50-150ms延迟）
    MAX_WORKERS = 2   # 2线程并行，避免触发风控
    success_count = 0
    failed_items = []
    start_time = time.time()
    results = {}

    print(f"[fanqie] 并行下载《{title}》{len(chapters)}章 ({MAX_WORKERS}线程) → {output_path}", file=sys.stderr)

    def _download_one(idx_ch):
        idx, ch = idx_ch
        item_id = ch.get("item_id", "")
        ch_title = ch.get("title", f"第{idx+1}章")
        time.sleep(random.uniform(0.05, 0.15))  # 50-150ms
        content = _fetch_chapter_direct(book_id, item_id)
        return idx, ch_title, content

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_download_one, (i, ch)): i for i, ch in enumerate(chapters)}
        for future in concurrent.futures.as_completed(futures):
            idx, ch_title, content = future.result()
            if content:
                results[idx] = (ch_title, content)
            else:
                failed_items.append(f"{ch_title}(空)")

    # 按顺序写入文件
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"《{title}》作者：{author}\n")
        f.write(f"来源：fanqienovel.com/page/{book_id}\n\n")
        for i in range(len(chapters)):
            if i in results:
                ch_title, content = results[i]
                f.write(f"\n{ch_title}\n\n{content}\n")
                success_count += 1

    elapsed = time.time() - start_time
    cn_chars = sum(len(c) for _, c in results.values()) if results else 0
    # 精确统计中文字数
    try:
        with open(output_path, encoding="utf-8") as f:
            cn_chars = sum(1 for c in f.read() if "\u4e00" <= c <= "\u9fff")
    except Exception:
        pass

    print(f"[fanqie] 完成: {success_count}/{len(chapters)} 章 | {elapsed:.0f}s | {cn_chars:,} 字 "
          f"({elapsed/len(chapters):.1f}s/章)", file=sys.stderr)
    if failed_items:
        print(f"[fanqie] 失败章节({len(failed_items)}): {', '.join(failed_items[:5])}", file=sys.stderr)

    return {
        "success": success_count > 0,
        "title": safe_title,
        "path": output_path if success_count > 0 else "",
        "cn_chars": cn_chars,
        "total_chapters": len(chapters),
        "downloaded": success_count,
        "failed_count": len(failed_items),
        "failed": failed_items[:10],
        "elapsed_seconds": round(elapsed, 1),
        "method": "fanqie_direct",
    }


def _try_download_zip(book_id: str, title: str, output_dir: str) -> dict:
    """尝试从 ixdzs8 下载 ZIP。"""
    safe_title = re.sub(r'[\\/:*?"<>|]', "_", title or book_id)
    zip_url = f"{BASE_DOWN}/{book_id}.zip"
    try:
        resp = safe_get(zip_url)
        if resp.status_code == 200 and len(resp.content) > 1000:
            return _extract_zip(resp.content, safe_title, output_dir)
        return {"success": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _extract_zip(zip_data: bytes, safe_title: str, output_dir: str) -> dict:
    """从 ZIP 字节流中提取 TXT 并保存。"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_data))
        txt_files = [f for f in zf.namelist() if f.lower().endswith(".txt")]
        if not txt_files:
            return {"success": False, "error": "ZIP 中没有 TXT 文件"}

        raw = zf.read(txt_files[0])

        # 编码检测
        text = None
        for enc in ["gb18030", "gbk", "utf-8"]:
            try:
                text = raw.decode(enc)
                if any("\u4e00" <= c <= "\u9fff" for c in text[:1000]):
                    break
            except (UnicodeDecodeError, UnicodeError):
                continue
        if text is None:
            text = raw.decode("utf-8", errors="replace")

        output_path = os.path.join(output_dir, f"{safe_title}.txt")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text)

        cn_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        return {
            "success": True,
            "title": safe_title,
            "path": output_path,
            "size_bytes": len(text.encode("utf-8")),
            "cn_chars": cn_chars,
            "method": "ixdzs8_zip",
        }
    except zipfile.BadZipFile:
        return {"success": False, "error": "ZIP 文件损坏"}


def cmd_chapters(book_id: str) -> dict:
    """获取章节列表（复用 info 的章节提取）。"""
    info = cmd_info(book_id)
    if info.get("found"):
        return {
            "book_id": book_id,
            "title": info.get("title", ""),
            "chapters": info.get("chapters", []),
            "count": info.get("chapter_count", 0),
        }
    return {"error": f"未找到章节: {book_id}"}


# ═══════════════════════════════════════════════════════════
# 书名 → book_id 解析器
# ═══════════════════════════════════════════════════════════

def _search_web_for_book_id(title: str) -> str:
    """通过 DuckDuckGo HTML 搜索 site:fanqienovel.com 提取 book_id。"""
    try:
        query = f'site:fanqienovel.com "{title}"'
        url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
        resp = safe_get(url)
        html = resp.text

        # 提取 fanqienovel.com/page/{book_id} 链接
        match = re.search(r'fanqienovel\.com/page/(\d+)', html)
        if match:
            return match.group(1)

        # 备选：提取 reader/{book_id} 链接
        match = re.search(r'fanqienovel\.com/reader/(\d+)', html)
        if match:
            # reader URL 的 ID 可能是章节 ID，尝试从 page URL 获取
            pass
    except Exception:
        pass
    return ""


def _search_bing_for_book_id(title: str) -> str:
    """通过 Bing 搜索 site:fanqienovel.com 提取 book_id。"""
    try:
        query = f'site:fanqienovel.com "{title}"'
        url = f"https://www.bing.com/search?q={quote(query)}"
        resp = safe_get(url)
        html = resp.text
        match = re.search(r'fanqienovel\.com/page/(\d+)', html)
        if match:
            return match.group(1)
    except Exception:
        pass
    return ""


def cmd_resolve(title: str) -> dict:
    """四级解析管线：书名 → book_id

    ① ixdzs8 搜索
    ② 番茄热榜匹配（已缓存的 trending 数据）
    ③ DuckDuckGo site:fanqienovel.com
    ④ Bing site:fanqienovel.com
    """
    results = []

    # 如果已经是纯数字 book_id 或 URL，直接返回
    if re.match(r"^\d{10,}$", title):
        return {
            "found": True,
            "book_id": title,
            "source": "direct",
            "title": title,
            "method": "direct_book_id",
        }
    # URL 提取 book_id
    url_match = re.search(r'fanqienovel\.com/page/(\d+)', title)
    if url_match:
        return {
            "found": True,
            "book_id": url_match.group(1),
            "source": "url",
            "title": title,
            "method": "url_extract",
        }

    # ① ixdzs8 搜索
    try:
        ix_results = ixdzs8_search(title, limit=5)
        for r in ix_results:
            if "error" not in r and r.get("book_id"):
                results.append({
                    "book_id": r["book_id"],
                    "title": r.get("title", ""),
                    "author": r.get("author", ""),
                    "source": "ixdzs8",
                    "download_method": "ixdzs8_zip",
                })
    except Exception:
        pass

    # ①b 番茄移动端 API 搜索
    try:
        mobile_results = fanqie_mobile_search(title, limit=10)
        for r in mobile_results:
            if "error" not in r and r.get("book_id"):
                bid = r["book_id"]
                if bid not in [x["book_id"] for x in results]:
                    results.append({
                        "book_id": bid,
                        "title": r.get("title", ""),
                        "author": r.get("author", ""),
                        "source": "fanqie_mobile",
                        "download_method": "fanqie_direct",
                    })
    except Exception:
        pass

    # ② 番茄热榜/榜单匹配
    try:
        trending = cmd_trending()
        all_lists = trending.get("results", {})
        for list_name, books in all_lists.items():
            for b in books:
                b_title = b.get("title", "")
                if title in b_title or b_title in title:
                    bid = b.get("book_id", "")
                    if bid and bid not in [r["book_id"] for r in results]:
                        results.append({
                            "book_id": bid,
                            "title": b_title,
                            "author": b.get("author", ""),
                            "source": "fanqie",
                            "download_method": "fanqie_direct",
                        })
    except Exception:
        pass

    # ③ DuckDuckGo
    fq_id = _search_web_for_book_id(title)
    if fq_id and fq_id not in [r["book_id"] for r in results]:
        results.append({
            "book_id": fq_id,
            "title": title,
            "author": "",
            "source": "fanqie",
            "download_method": "fanqie_direct",
        })

    # ④ Bing 回退
    if not any(r["source"] == "fanqie" for r in results):
        fq_id2 = _search_bing_for_book_id(title)
        if fq_id2 and fq_id2 not in [r["book_id"] for r in results]:
            results.append({
                "book_id": fq_id2,
                "title": title,
                "author": "",
                "source": "fanqie",
                "download_method": "fanqie_direct",
            })

    if results:
        return {
            "found": True,
            "results": results,
            "best": results[0],
            "count": len(results),
        }

    return {
        "found": False,
        "error": f"未找到「{title}」的书籍 ID。请尝试直接输入 book_id 或完整 URL。",
        "searched": ["ixdzs8", "DuckDuckGo", "Bing"],
    }


# ═══════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════

COMMANDS = {
    "search": (cmd_search, "keyword"),
    "info": (cmd_info, "book_id"),
    "trending": (cmd_trending,),
    "rank": (cmd_rank, "category_id"),
    "download": (cmd_download, "book_id", "output_dir"),
    "download_fanqie": (cmd_download_fanqie, "book_id", "output_dir"),
    "chapters": (cmd_chapters, "book_id"),
    "resolve": (cmd_resolve, "title"),
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(json.dumps({
            "error": f"用法: bridge.py <{'|'.join(COMMANDS)}> [args...]"
        }, ensure_ascii=False))
        sys.exit(1)

    cmd = sys.argv[1]
    handler = COMMANDS[cmd][0]
    args = sys.argv[2:]

    try:
        result = handler(*args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
