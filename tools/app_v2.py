"""
Windows 窗口程序：后台起 Web 模式，再用 pywebview 开一个原生窗口显示新界面。

    .venv\\Scripts\\python.exe tools\\app_v2.py                 # 随机端口，系统标题栏
    .venv\\Scripts\\python.exe tools\\app_v2.py --port 8765     # 固定端口，顺便能用浏览器/okctl 访问
    .venv\\Scripts\\python.exe tools\\app_v2.py --frameless     # 无边框 + 界面自绘标题栏（和 MXU 一样）

关掉窗口就退出（会停掉后端）。和桌面版（main.py）不能同时运行。
"""

import argparse
import os
import socket
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from serve_web_v2 import build_app  # noqa: E402

WINDOW_TITLE = "少前2 自动化"


class WindowApi:
    """给网页里的自绘标题栏用（window.pywebview.api.*）。

    注意：pywebview 会递归遍历 js_api 的所有公开属性来生成 JS 接口，
    Window 对象必须放在下划线开头的私有属性里，否则它会从工作线程去碰
    window.native（WebView2 COM 对象），和 UI 线程互相等待，整个进程卡死。
    """

    def __init__(self):
        self._window = None
        self._maximized = False

    def minimize(self):
        if self._window:
            self._window.minimize()

    def toggle_maximize(self):
        if not self._window:
            return False
        if self._maximized:
            self._window.restore()
        else:
            self._window.maximize()
        self._maximized = not self._maximized
        return self._maximized

    def close(self):
        if self._window:
            self._window.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="0 = 随机端口")
    parser.add_argument("--frameless", action="store_true", help="无边框窗口，用界面自绘的标题栏")
    args = parser.parse_args()

    app, uvicorn = build_app()
    import webview

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((args.host, args.port))
    sock.listen(64)
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=port, log_config=None))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, name="web-server", daemon=True)
    thread.start()

    url = f"http://{args.host}:{port}/v2/" + ("?frameless=1" if args.frameless else "")
    print(f"ok-gf2 window: {url}", flush=True)
    webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False
    api = WindowApi()
    window = webview.create_window(
        WINDOW_TITLE,
        url,
        js_api=api,
        width=1420,
        height=880,
        min_size=(1000, 640),
        frameless=args.frameless,
        easy_drag=False,
    )
    api._window = window
    try:
        webview.start()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()


if __name__ == "__main__":
    main()
