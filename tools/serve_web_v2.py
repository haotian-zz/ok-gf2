"""
以 Web 模式启动 ok-gf2，并把新界面（web_v2/static，Vite 构建产物）挂到 /v2。

    .venv\\Scripts\\python.exe tools\\serve_web_v2.py            # 默认 127.0.0.1:8765
    .venv\\Scripts\\python.exe tools\\serve_web_v2.py --port 8800

浏览器打开 http://127.0.0.1:8765/v2/ 。框架自带的旧网页仍在 /，不再维护。
要以 Windows 窗口方式打开，用 tools/app_v2.py（或 run_v2.bat）。
Web 模式和桌面版（main.py）不能同时运行。
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_V2_DIR = os.path.join(ROOT, "web_v2", "static")


def build_app():
    """建好带 /v2 的 FastAPI 应用，返回 (app, uvicorn 模块)。"""
    os.chdir(ROOT)
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from fastapi.responses import FileResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles
    from ok.ui.web.app import create_web_app
    from ok.ui.web.requirements import check_web_requirements
    from ok.ui.web.server import _configure_server_logging

    from src.config import config

    index = os.path.join(WEB_V2_DIR, "index.html")
    if not os.path.exists(index):
        raise SystemExit(
            f"没有找到新界面的构建产物 {index}。\n"
            "仓库里应随 git 提交；如果是本地开发，先在 web_v2/ 里跑 npm install && npm run build。"
        )

    uvicorn = check_web_requirements()
    web_config = dict(config)
    web_config["use_gui"] = False
    app = create_web_app(web_config)

    @app.get("/v2")
    async def v2_redirect():
        return RedirectResponse("/v2/")

    @app.get("/v2/")
    async def v2_index():
        return FileResponse(index)

    app.mount("/v2", StaticFiles(directory=WEB_V2_DIR), name="web_v2")
    _configure_server_logging()
    return app, uvicorn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    app, uvicorn = build_app()
    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port, log_config=None))
    print(f"ok-gf2 web: http://{args.host}:{args.port}/v2/", flush=True)
    server.run()


if __name__ == "__main__":
    main()
