"""LordBlack Harness — launcher.

Starts the local FastAPI backend, serves the static UI (lordblack/web/index.html)
and opens the app in your default browser. Clone-or-download-and-run: no Docker,
no Node build step.

Usage:
    python app.py                 # default port 8000
    python app.py --port 9000     # custom port
    LORDBLACK_HOST=0.0.0.0 python app.py   # expose on LAN (agents hosting)
"""
from __future__ import annotations

import argparse
import os
import threading
import time
import webbrowser

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from lordblack import __version__
from lordblack.routers import agents_api, chat, cloud_api, files, memory_api, system
from lordblack.services import activity

WEB_DIR = os.path.join(os.path.dirname(__file__), "lordblack", "web")


def create_app() -> FastAPI:
    app = FastAPI(title="LordBlack Harness", version=__version__, docs_url="/api/docs")

    # API routers
    app.include_router(system.router)
    app.include_router(chat.router)
    app.include_router(memory_api.router)
    app.include_router(files.router)
    app.include_router(cloud_api.router)
    app.include_router(agents_api.router)

    # Static assets (css/js) + index page
    app.mount("/static", StaticFiles(directory=os.path.join(WEB_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(os.path.join(WEB_DIR, "index.html"))

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        ico = os.path.join(WEB_DIR, "favicon.ico")
        if os.path.exists(ico):
            return FileResponse(ico)
        return FileResponse(os.path.join(WEB_DIR, "index.html"))

    return app


def _open_browser(url: str) -> None:
    # give uvicorn a moment to bind before the browser hits it
    time.sleep(1.2)
    try:
        webbrowser.open(url)
    except Exception:
        pass  # headless box — user can open the URL manually


def main() -> None:
    parser = argparse.ArgumentParser(description="LordBlack Harness launcher")
    parser.add_argument("--host", default=os.environ.get("LORDBLACK_HOST", "127.0.0.1"),
                        help="Bind address. Default 127.0.0.1 (localhost only). "
                             "Use 0.0.0.0 to also reach hosted agents from the LAN.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("LORDBLACK_PORT", "8000")))
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open the UI.")
    args = parser.parse_args()

    url = f"http://{'localhost' if args.host in ('0.0.0.0', '127.0.0.1') else args.host}:{args.port}"
    print(f"LordBlack Harness v{__version__}")
    print(f"  UI:        {url}")
    print(f"  API docs:  {url}/api/docs")
    print(f"  Agents:    {url}/agents/<name>  (LAN reachable if bound 0.0.0.0)")
    print("Ctrl+C to stop.\n")

    if not args.no_browser:
        threading.Thread(target=_open_browser, args=(url,), daemon=True).start()

    activity.log("system", "ok", f"harness starting on {args.host}:{args.port}")
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
