"""
新版界面的 Windows 窗口程序：后台起 Web 模式，再用 pywebview 开一个原生窗口显示 /v2/。

    .venv\\Scripts\\python.exe tools\\app_v2.py             # 随机端口
    .venv\\Scripts\\python.exe tools\\app_v2.py --port 8765 # 固定端口，顺便能用浏览器/okctl 访问

关掉窗口就退出（会停掉后端）。和桌面版（main.py）不能同时运行。
"""

import argparse
import os
import socket
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from serve_web_v2 import build_app  # noqa: E402

WINDOW_TITLE = "少前2 自动化 · 新版界面（测试）"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="0 = 随机端口")
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

    url = f"http://{args.host}:{port}/v2/"
    print(f"ok-gf2 v2 window: {url}", flush=True)
    webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False
    webview.create_window(WINDOW_TITLE, url, width=1420, height=880, min_size=(1000, 640))
    try:
        webview.start()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()


if __name__ == "__main__":
    main()
