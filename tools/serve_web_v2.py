"""
以 Web 模式启动 ok-gf2，并额外挂载新版界面（web_v2/）到 /v2，旧界面仍在 /。

    .venv\\Scripts\\python.exe tools\\serve_web_v2.py            # 默认 127.0.0.1:8765
    .venv\\Scripts\\python.exe tools\\serve_web_v2.py --port 8800

浏览器打开 http://127.0.0.1:8765/v2/ 看新版，http://127.0.0.1:8765/ 看旧版。
两个页面共用同一套 /api 接口（任务、配置、全局设置、日志、截图、事件推送），互不影响。
Web 模式和桌面版（main.py）不能同时运行。
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_V2_DIR = os.path.join(ROOT, "web_v2")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    os.chdir(ROOT)
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    from ok.ui.web.app import create_web_app
    from ok.ui.web.requirements import check_web_requirements
    from ok.ui.web.server import _configure_server_logging

    from src.config import config

    uvicorn = check_web_requirements()
    web_config = dict(config)
    web_config["use_gui"] = False
    app = create_web_app(web_config)

    @app.get("/v2")
    @app.get("/v2/")
    async def v2_index():
        return FileResponse(os.path.join(WEB_V2_DIR, "index.html"))

    app.mount("/v2", StaticFiles(directory=WEB_V2_DIR), name="web_v2")

    _configure_server_logging()
    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port, log_config=None))
    print(f"ok-gf2 web: old UI http://{args.host}:{args.port}/  new UI http://{args.host}:{args.port}/v2/", flush=True)
    server.run()


if __name__ == "__main__":
    main()
