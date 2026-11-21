"""Starts the dashboard:  python -m dashboard  [--port 8000] [--no-browser]"""

import argparse
import contextlib
import threading
import webbrowser

import uvicorn

from .app import create_app


class Server(uvicorn.Server):
    """Ctrl+C first ends the video streams: they never finish on their own, and uvicorn waits for open connections."""

    def handle_exit(self, sig, frame):
        self.config.app.state.closing.set()
        super().handle_exit(sig, frame)


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
    config = uvicorn.Config(create_app(), host=args.host, port=args.port, log_level="warning",
                            timeout_graceful_shutdown=5)
    with contextlib.suppress(KeyboardInterrupt):  # uvicorn re-raises Ctrl+C after it has shut down
        Server(config).run()


if __name__ == "__main__":
    main()
