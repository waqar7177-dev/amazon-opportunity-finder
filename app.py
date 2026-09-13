"""Start Amazon UK Opportunity Finder.

    python app.py               start on http://127.0.0.1:8877
    python app.py --init-only   create the data folder and database, then exit
    python app.py --no-browser  do not open a browser tab
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import webbrowser

from config import Config
from opportunity_finder.app_factory import create_app
from opportunity_finder.constants import APP_NAME, APP_VERSION

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def port_is_free(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--port", type=int, help="port to listen on (default 8877 or AOF_PORT)")
    parser.add_argument("--init-only", action="store_true", help="set up the data folder and database, then exit")
    browser = parser.add_mutually_exclusive_group()
    browser.add_argument("--open-browser", dest="open_browser", action="store_true", default=None)
    browser.add_argument("--no-browser", dest="open_browser", action="store_false")
    args = parser.parse_args(argv)

    config = Config()
    if args.port:
        config.PORT = args.port
    app = create_app(config)

    if args.init_only:
        print(f"Database ready: {config.DATABASE_PATH}")
        return 0

    display_host = "127.0.0.1" if config.HOST in ("0.0.0.0", "::") else config.HOST
    url = f"http://{display_host}:{config.PORT}"
    if not port_is_free(config.HOST, config.PORT):
        print(f"\n  Port {config.PORT} is already in use — the app may already be running.")
        print(f"  Open {url} in your browser, or start on another port: python app.py --port 8878\n")
        return 1

    # The launch scripts print no address of their own: this banner reads the same config the server uses.
    banner = ["=" * 64, f"  {APP_NAME} v{APP_VERSION}", f"  Open:  {url}", f"  Data:  {config.DATA_DIR}",
              "  Stop:  press Ctrl+C in this window", "=" * 64]
    if config.HOST not in LOCAL_HOSTS:
        banner.append(f"  WARNING: listening on {config.HOST} — other devices on your network can reach this app.")
    print("\n".join(banner), flush=True)

    open_browser = config.OPEN_BROWSER if args.open_browser is None else args.open_browser
    if open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    try:
        from waitress import serve
    except ImportError:  # pragma: no cover - waitress is in requirements.txt
        app.run(host=config.HOST, port=config.PORT, debug=False)
        return 0
    serve(app, host=config.HOST, port=config.PORT, threads=6, ident=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
