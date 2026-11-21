"""Multiplayer: a second person (a teammate or a judge) controls one arm from another laptop.

One laptop, the host, runs everything. A guest only opens a web page:

    guest browser ──HTTPS──> Cloudflare ──tunnel──> cloudflared on the host ──> dashboard on localhost:8000

- Public link: cloudflared makes a "quick tunnel": a random address https://<words>.trycloudflare.com, new at every
  start, no Cloudflare account needed. The host starts and stops it in the Players panel.
- Who is a guest: every request that came through Cloudflare carries the header Cf-Connecting-Ip (Cloudflare sets
  it; a browser cannot remove it). Requests without it come from the host laptop itself.
- Access code: a guest must type the code once (the host sees it in the Players panel). It is new at every start of
  the dashboard. After 10 wrong codes from one address, that address waits 10 minutes.
- What a guest may do: watch, and move the ONE arm they took. Everything else (Run, Stop, Reset, settings,
  robustness, episodes, credits) is for the host only.
- Arms: each arm has at most one owner. A guest must take an arm before moving it. The host can move every arm that
  no guest owns, and can free an arm a guest took.
- Picture: guests get the main view smaller (640 x 360) and less often (12 per second), which needs about a third of
  the internet bandwidth. Guests cannot turn the shared 3D view; they can switch to the robot cameras.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from pathlib import Path

SIDES = ("left", "right")
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I: easy to read aloud
MAX_FAILURES, LOCK_SECONDS = 10, 600
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

## Requests a guest may send besides reading (GET).
GUEST_POSTS = {"/api/join", "/api/players/claim", "/api/players/release", "/api/players/name",
               "/api/ext/teleop/jog", "/api/ext/teleop/drag", "/api/ext/teleop/gripper", "/api/ext/teleop/orientation"}
## Requests that move one arm: the body names the arm ("side").
ARM_POSTS = {"/api/ext/teleop/jog", "/api/ext/teleop/drag", "/api/ext/teleop/gripper"}
## Pages a guest may open before typing the code.
OPEN_PATHS = {"/join", "/api/join", "/static/style.css", "/static/join.js"}
## Host-only GET requests (they show the code or local paths).
HOST_ONLY_GETS = ("/api/players/tunnel",)


def new_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def is_remote(headers) -> bool:
    """Whether a request came through the Cloudflare tunnel."""
    return "cf-connecting-ip" in headers or "cf-ray" in headers


class PlayerError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class Players:
    def __init__(self, bus, code: str | None = None):
        self.bus = bus
        self.code = code or os.environ.get("DREAM_ACCESS_CODE") or new_code()
        self.lock = threading.Lock()
        self.tokens: dict[str, str] = {}  # guest cookie token -> client id
        self.clients: dict[str, dict] = {}  # client id -> {"name", "role", "seen"}
        self.owners: dict[str, str | None] = {side: None for side in SIDES}
        self.failures: dict[str, list] = {}  # ip -> [count, locked_until]
        self.guest_viewers = 0  # open low-quality video streams
        self.tunnel = Tunnel(self)

    # ---------- identity ----------

    def seen(self, client: str, role: str) -> None:
        with self.lock:
            entry = self.clients.setdefault(client, {"name": "Host" if role == "host" else "Guest", "role": role})
            entry["seen"], entry["role"] = time.time(), role

    def guest_client(self, token: str | None) -> str | None:
        return self.tokens.get(token or "")

    def join(self, ip: str, code: str, name: str) -> tuple[str, str]:
        """Checks the access code. Returns (cookie token, client id)."""
        now = time.time()
        with self.lock:
            count, until = self.failures.get(ip, [0, 0.0])
            if until > now:
                raise PlayerError(429, f"Too many wrong codes. Try again in {int(until - now) // 60 + 1} minutes.")
            typed = re.sub(r"[\s-]", "", code).upper()  # "abcd efgh" and "ABCD-EFGH" both count
            if not secrets.compare_digest(typed, self.code.replace("-", "")):
                count += 1
                self.failures[ip] = [count, now + LOCK_SECONDS if count >= MAX_FAILURES else 0.0]
                raise PlayerError(403, "Wrong access code.")
            self.failures.pop(ip, None)
            token, client = secrets.token_urlsafe(24), "g-" + secrets.token_hex(6)
            self.tokens[token] = client
            self.clients[client] = {"name": (name.strip() or "Guest")[:40], "role": "guest", "seen": now}
        self.changed()
        return token, client

    def rename(self, client: str, name: str) -> None:
        with self.lock:
            if client in self.clients:
                self.clients[client]["name"] = (name.strip() or self.clients[client]["name"])[:40]
        self.changed()

    # ---------- arms ----------

    def claim(self, client: str, side: str, role: str) -> None:
        if side not in SIDES:
            raise PlayerError(400, "The arm must be left or right.")
        with self.lock:
            owner = self.owners[side]
            if owner not in (None, client):
                name = self.clients.get(owner, {}).get("name", "someone")
                if role != "host":
                    raise PlayerError(409, f"The {side} arm belongs to {name}.")
            if role == "guest":  # a guest holds at most one arm
                for s in SIDES:
                    if self.owners[s] == client:
                        self.owners[s] = None
            self.owners[side] = client
        self.changed()

    def release(self, client: str, side: str | None, role: str) -> None:
        with self.lock:
            for s in ([side] if side else SIDES):
                if s in SIDES and (self.owners[s] == client or role == "host"):
                    self.owners[s] = None
        self.changed()

    def may_move(self, client: str, side: str, role: str) -> str | None:
        """None when this client may move this arm, else the reason why not."""
        owner = self.owners.get(side)
        if role == "guest" and owner != client:
            return f"Take the {side} arm first (Players panel)." if owner is None else \
                f"The {side} arm belongs to {self.clients.get(owner, {}).get('name', 'someone')}."
        if role == "host" and owner not in (None, client) and self.clients.get(owner, {}).get("role") == "guest":
            return f"The {side} arm belongs to {self.clients[owner]['name']}. Free it in the Players panel first."
        return None

    # ---------- state ----------

    def state(self, client: str | None = None, role: str = "host") -> dict:
        now = time.time()
        with self.lock:
            players = [{"id": cid, "name": c["name"], "role": c["role"], "online": now - c.get("seen", 0) < 30,
                        "arm": next((s for s in SIDES if self.owners[s] == cid), None)}
                       for cid, c in self.clients.items() if c["role"] == "guest" or cid == client]
            owners = {s: (None if o is None else {"id": o, "name": self.clients.get(o, {}).get("name", "?")})
                      for s, o in self.owners.items()}
        data = {"me": {"id": client, "role": role,
                       "name": self.clients.get(client, {}).get("name") if client else None,
                       "arm": next((s for s in SIDES if self.owners[s] == client), None)},
                "owners": owners, "players": players, "link": self.tunnel.url,
                "tunnel": self.tunnel.status()}
        if role == "host":
            data["code"] = self.code
        return data

    def changed(self) -> None:
        # The code is never sent over the event bus: guests receive those events too.
        self.bus.emit("players.state", {"owners": {s: (None if o is None else
                                                       self.clients.get(o, {}).get("name", "?"))
                                                   for s, o in self.owners.items()},
                                        "link": self.tunnel.url, "tunnel": self.tunnel.status()})


class Tunnel:
    """cloudflared as a child process: `cloudflared tunnel --url http://localhost:<port>`."""

    def __init__(self, players: Players):
        self.players = players
        self.proc: subprocess.Popen | None = None
        self.url: str | None = None
        self.error: str | None = None
        self.lines: list[str] = []

    @staticmethod
    def binary() -> str | None:
        for candidate in (os.environ.get("CLOUDFLARED"), shutil.which("cloudflared"),
                          str(Path.home() / "Hacklab" / "bin" / "cloudflared")):
            if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
                return candidate
        return None

    def status(self) -> str:
        if self.proc is not None and self.proc.poll() is None:
            return "open" if self.url else "starting"
        return "error" if self.error else "closed"

    def start(self, port: int) -> None:
        if self.status() in ("open", "starting"):
            return
        binary = self.binary()
        if binary is None:
            raise PlayerError(400, "cloudflared is not installed on this laptop. See README, Multiplayer.")
        self.url, self.error, self.lines = None, None, []
        self.proc = subprocess.Popen([binary, "tunnel", "--no-autoupdate", "--url", f"http://localhost:{port}"],
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        threading.Thread(target=self._read, args=(self.proc,), name="cloudflared", daemon=True).start()
        self.players.changed()

    def _read(self, proc) -> None:
        for line in proc.stdout:
            self.lines = (self.lines + [line.rstrip()])[-40:]
            match = URL_RE.search(line)
            if match and not self.url:
                self.url = match[0]
                self.players.bus.log(f"Public link open: {self.url}")
                self.players.changed()
        if self.proc is proc:
            code = proc.wait()
            if code not in (0, -15) and not self.url:
                self.error = "cloudflared stopped: " + (self.lines[-1] if self.lines else f"exit code {code}")
                self.players.bus.log(self.error, "error")
            self.url = None
            self.players.changed()

    def stop(self) -> None:
        proc, self.proc = self.proc, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
        self.url, self.error = None, None
        self.players.changed()
