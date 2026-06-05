"""fanqie-desktop-remake 任务队列
异步下载管理：提交 → 后台执行 → 进度轮询
解决同步下载超时问题。
"""

import json, os, threading, time, uuid, pathlib
from datetime import datetime
from collections import OrderedDict

TASKS_FILE = pathlib.Path(__file__).parent / "tasks.json"
MAX_TASKS = 50  # 最多保留50条任务记录

_tasks: OrderedDict = OrderedDict()
_lock = threading.Lock()


def _load():
    global _tasks
    if TASKS_FILE.exists():
        try:
            with open(TASKS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            _tasks = OrderedDict()
            for k, v in sorted(data.items(), key=lambda x: x[1].get("created_at", ""), reverse=True):
                _tasks[k] = v
        except Exception:
            _tasks = OrderedDict()


def _save():
    with _lock:
        # 只保留最近 MAX_TASKS 条
        items = list(_tasks.items())[:MAX_TASKS]
        with open(TASKS_FILE, "w", encoding="utf-8") as f:
            json.dump(dict(items), f, ensure_ascii=False, indent=2)


def create_task(book_id: str, output_dir: str = None) -> dict:
    """创建下载任务，返回 task_id。"""
    task_id = str(uuid.uuid4())[:8]
    task = {
        "task_id": task_id,
        "book_id": book_id,
        "output_dir": output_dir or str(pathlib.Path.home() / "Downloads" / "FanqieNovels"),
        "status": "pending",
        "progress": 0,
        "total": 0,
        "created_at": datetime.now().isoformat(),
        "result": None,
    }
    with _lock:
        _tasks[task_id] = task
        _save()
    return task


def update_task(task_id: str, **kwargs):
    """更新任务状态、进度等。"""
    with _lock:
        if task_id in _tasks:
            _tasks[task_id].update(kwargs)
            _save()


def get_task(task_id: str) -> dict | None:
    with _lock:
        return _tasks.get(task_id)


def get_all_tasks() -> list[dict]:
    with _lock:
        return list(_tasks.values())


def run_download(task_id: str):
    """后台执行下载（在线程中运行）。"""
    task = get_task(task_id)
    if not task or task["status"] != "pending":
        return

    update_task(task_id, status="downloading")

    # 导入 bridge 函数（延迟导入避免循环依赖）
    from bridge import cmd_info, cmd_download_fanqie

    try:
        # 获取书籍信息
        info = cmd_info(task["book_id"])
        title = info.get("title", task["book_id"])
        chapters = info.get("chapters", [])
        update_task(task_id, total=len(chapters), title=title)

        # 下载
        result = cmd_download_fanqie(task["book_id"], task["output_dir"])

        if result.get("success"):
            update_task(task_id,
                status="completed",
                progress=result.get("downloaded", 0),
                result={
                    "title": result.get("title"),
                    "path": result.get("path"),
                    "cn_chars": result.get("cn_chars"),
                    "downloaded": result.get("downloaded"),
                    "total_chapters": result.get("total_chapters"),
                    "elapsed_seconds": result.get("elapsed_seconds"),
                })
        else:
            update_task(task_id,
                status="failed",
                result={"error": result.get("error", "下载失败")})
    except Exception as e:
        update_task(task_id, status="failed", result={"error": str(e)})


def submit_and_run(book_id: str, output_dir: str = None) -> dict:
    """提交任务并在后台执行，立即返回 task_id。"""
    task = create_task(book_id, output_dir)
    t = threading.Thread(target=run_download, args=(task["task_id"],), daemon=True)
    t.start()
    return task


# 启动时加载
_load()
