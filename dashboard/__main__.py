"""Starts the dashboard:  python -m dashboard  [--port 8000] [--no-browser]"""

import argparse
import threading
import webbrowser

import uvicorn

from .app import create_app


def main():
    parser = argparse.ArgumentParser(prog="python -m dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="127.0.0.1 = this machine only")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    url = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}"
    print(f"Dream-1 Dashboard: {url}  (Ctrl+C to quit)")
    if not args.no_browser:
        threading.Timer(2.5, webbrowser.open, args=(url,)).start()
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
