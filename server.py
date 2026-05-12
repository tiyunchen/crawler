"""
本地查看服务器
==============
- 静态文件服务（替代 python -m http.server）
- /api/sync  → 后台触发 toutiao_crawler.py
- /api/sync/status → 查询同步状态
"""

import http.server
import json
import os
import subprocess
import threading
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
PORT = int(os.environ.get("PORT", 8000))

# ---------- 同步状态 ----------
sync_state = {
    "running": False,
    "last_start": None,
    "last_end": None,
    "last_exit_code": None,
    "error": None,
    "new_count": 0,
}
sync_lock = threading.Lock()

ARTICLES_JSON = PROJECT_DIR / "output_toutiao" / "articles.json"


def _count_articles():
    """读取 articles.json 返回当前文章数量"""
    try:
        with open(ARTICLES_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        return len(data) if isinstance(data, list) else 0
    except (FileNotFoundError, json.JSONDecodeError):
        return 0


def run_crawler():
    """在后台线程中执行爬虫脚本"""
    global sync_state
    python = PROJECT_DIR / ".venv" / "bin" / "python"
    script = PROJECT_DIR / "toutiao_crawler.py"

    env = os.environ.copy()
    env["HEADLESS"] = "1"

    # 记录同步前的文章数
    count_before = _count_articles()

    try:
        proc = subprocess.Popen(
            [str(python), str(script)],
            cwd=str(PROJECT_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        proc.wait()

        # 计算新增文章数
        count_after = _count_articles()
        new_count = max(0, count_after - count_before)

        with sync_lock:
            sync_state["running"] = False
            sync_state["last_end"] = time.strftime("%Y-%m-%d %H:%M:%S")
            sync_state["last_exit_code"] = proc.returncode
            sync_state["new_count"] = new_count
            sync_state["error"] = None if proc.returncode == 0 else f"exit code {proc.returncode}"
    except Exception as e:
        with sync_lock:
            sync_state["running"] = False
            sync_state["last_end"] = time.strftime("%Y-%m-%d %H:%M:%S")
            sync_state["last_exit_code"] = -1
            sync_state["new_count"] = 0
            sync_state["error"] = str(e)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PROJECT_DIR), **kwargs)

    def do_POST(self):
        if self.path == "/api/sync":
            self.handle_sync()
        else:
            self.send_error(404)

    def do_GET(self):
        if self.path == "/api/sync/status":
            self.handle_status()
        else:
            super().do_GET()

    def handle_sync(self):
        global sync_state
        with sync_lock:
            if sync_state["running"]:
                self.json_response(200, {"ok": False, "message": "同步正在进行中，请稍后再试"})
                return
            sync_state["running"] = True
            sync_state["last_start"] = time.strftime("%Y-%m-%d %H:%M:%S")
            sync_state["last_end"] = None
            sync_state["last_exit_code"] = None
            sync_state["error"] = None

        t = threading.Thread(target=run_crawler, daemon=True)
        t.start()
        self.json_response(200, {"ok": True, "message": "同步已启动"})

    def handle_status(self):
        with sync_lock:
            data = dict(sync_state)
        self.json_response(200, data)

    def json_response(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # 静默日志
    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    print(f"🌐 服务已启动：http://localhost:{PORT}/viewer.html")
    print(f"🔄 同步接口：POST http://localhost:{PORT}/api/sync")
    print("🛑 停止服务：Ctrl+C")
    server = http.server.HTTPServer(("", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 服务已停止")
