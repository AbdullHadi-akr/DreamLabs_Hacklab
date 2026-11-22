"""FastAPI app: HTTP API, video streams (MJPEG), WebSocket events, extension routes."""

from __future__ import annotations

import asyncio
import contextlib
import json
import mimetypes
import threading
import secrets
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints

from dreamtool import inference, scene
from dreamtool import sim as dsim

from . import brain, credits

from .episodes import Recorder
from .episodes import export as export_episodes
from .events import EventBus
from .extension import describe, load_extensions
from .lab_db import LabDB
from .multiplayer import ARM_POSTS, GUEST_POSTS, HOST_ONLY_GETS, OPEN_PATHS, PlayerError, Players, is_remote
from .simulation import CAMERAS, MAIN_FPS, SimWorker, demo_motion

## Windows reads MIME types from the registry, which often maps .js to text/plain -> browsers refuse ES modules.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")

STATIC = Path(__file__).parent / "static"
TASK_SUGGESTIONS = [
    "put apple into the bowl",
    "put orange into the bowl",
    "put banana on the plate",
    "put apple on the plate",
    *(rule["example"] for rule in scene.describe_rules()),
]
EXT_FILE_TYPES = {".js", ".css", ".html", ".svg", ".png", ".jpg", ".json"}


class RunBody(BaseModel):
    task: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=300)]
    model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)] = dsim.BETA_MODEL
    seconds: float = Field(60, gt=0, le=3600)
    offline: bool = False
    strategy: str = inference.DEFAULT


class RecordBody(BaseModel):
    enabled: bool


class ExportBody(BaseModel):
    task: str = Field(min_length=2, max_length=300)
    name: str = Field(pattern=r"^[a-z0-9-]{1,64}$")


class CreditSettingsBody(BaseModel):
    start_balance_usd: float | None = Field(None, ge=0, le=1_000_000)
    monthly_limit_usd: float | None = Field(None, ge=0, le=1_000_000)
    confirm_above_usd: float | None = Field(None, ge=0, le=1_000_000)


class JoinBody(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field("", max_length=40)


class SideBody(BaseModel):
    side: str | None = Field(None, pattern=r"^(left|right)$")


class NameBody(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class TunnelBody(BaseModel):
    open: bool


class CameraBody(BaseModel):
    lookat: list[float] | None = None
    distance: float | None = None
    azimuth: float | None = None
    elevation: float | None = None
    reset: bool = False


def _quiet_disconnects(loop, context):
    """Windows' asyncio logs a traceback whenever a browser drops a connection (a closed camera stream, a reload):
    ConnectionResetError [WinError 10054] while shutting the socket down. Harmless; every other error is logged."""
    if isinstance(context.get("exception"), ConnectionResetError):
        return
    loop.default_exception_handler(context)


def create_app() -> FastAPI:
    bus = EventBus()
    db = LabDB()
    recorder = Recorder(db, bus)
    worker = SimWorker(bus, db=db, recorder=recorder)
    players = Players(bus)
    extensions = load_extensions(worker, bus)
    worker.extensions = extensions
    campaigns = getattr(worker, "campaign_recovery", None)
    controls_lock = campaigns.lock if campaigns else threading.RLock()

    def campaign_active():
        return campaigns is not None and campaigns.active is not None

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        bus.bind(asyncio.get_running_loop())
        asyncio.get_running_loop().set_exception_handler(_quiet_disconnects)
        worker.start()
        await asyncio.get_running_loop().run_in_executor(None, worker.ready.wait, 60)
        yield
        for ext in extensions:
            with contextlib.suppress(Exception):
                ext.shutdown()
        players.tunnel.stop()
        worker.shutdown()
        await asyncio.get_running_loop().run_in_executor(None, worker.join, 5)

    app = FastAPI(title="Dream-1 Dashboard", lifespan=lifespan)
    app.state.bus, app.state.sim, app.state.extensions = bus, worker, extensions
    ## Set by the server on Ctrl+C (see __main__.py): ends the endless video streams, otherwise shutdown waits forever.
    app.state.closing = closing = threading.Event()
    app.state.db, app.state.recorder, app.state.players = db, recorder, players

    @app.middleware("http")
    async def no_cache(request, call_next):
        """While developing: edited JS/CSS files show up immediately after a reload."""
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.middleware("http")
    async def access(request: Request, call_next):
        """Who is asking: the host laptop itself, or a guest through the Cloudflare tunnel (dashboard/multiplayer.py).
        Guests need the access code, may only read and move their own arm."""
        path, new_client = request.url.path, None
        if is_remote(request.headers):
            client, role = players.guest_client(request.cookies.get("dream_guest")), "guest"
            if client is None:
                if path in OPEN_PATHS:
                    return await call_next(request)
                if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
                    return RedirectResponse("/join", status_code=303)
                return JSONResponse({"detail": "Type the access code first."}, status_code=401)
            if (request.method not in ("GET", "HEAD") and path not in GUEST_POSTS) or path.startswith(HOST_ONLY_GETS):
                return JSONResponse({"detail": "Only the host laptop can do this."}, status_code=403)
        else:
            client, role = request.cookies.get("dream_client"), "host"
            if not client or not client.startswith("h-"):
                client = new_client = "h-" + secrets.token_hex(6)
        request.state.client, request.state.role = client, role
        players.seen(client, role)
        if path in ARM_POSTS and request.method == "POST":
            try:
                side = json.loads((await request.body()) or b"{}").get("side")
            except (ValueError, AttributeError):
                side = None
            reason = players.may_move(client, side, role) if side in ("left", "right") else None
            if reason:
                return JSONResponse({"detail": reason}, status_code=409)
        response = await call_next(request)
        if new_client:
            response.set_cookie("dream_client", new_client, httponly=True, samesite="lax", max_age=30 * 86400)
        return response

    # ---------- pages & files ----------

    @app.get("/join")
    def join_page():
        return FileResponse(STATIC / "join.html")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/ext/{ext_id}/{filename}")
    def extension_file(ext_id: str, filename: str):
        ext = next((e for e in extensions if e.id == ext_id), None)
        path = (ext.folder / filename).resolve() if ext else None
        if not path or path.parent != ext.folder.resolve() or path.suffix not in EXT_FILE_TYPES or not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, headers={"Cache-Control": "no-store"})

    # ---------- core API ----------

    @app.get("/api/state")
    def state(request: Request):
        config = dsim.settings()
        return {
            "has_api_key": bool(config.get("DREAM_API_KEY")),
            "default_model": dsim.BETA_MODEL,
            "tasks": TASK_SUGGESTIONS,
            "cameras": list(CAMERAS),
            "strategies": [inference.parse(s).describe() for s in inference.PRESETS],
            "default_strategy": inference.DEFAULT,
            "camera": worker.camera.get(),
            "status": worker.status(),
            "sim": worker.state_snapshot,
            "extensions": [describe(e) for e in extensions],
            "episode": recorder.status(),
            "me": {"role": request.state.role, "id": request.state.client},
            "rules": scene.describe_rules(),
        }

    reset_job = None

    def require_idle():
        if not worker.ready.is_set() or worker.error:
            raise HTTPException(503, "The simulator is unavailable.")
        if worker.busy or campaign_active() or (reset_job is not None and not reset_job.done()):
            raise HTTPException(409, "A run is already active (or queued). Stop it first.")

    @app.post("/api/run")
    def run(body: RunBody):
        with controls_lock:
            require_idle()
            if not body.offline and not dsim.settings().get("DREAM_API_KEY"):
                raise HTTPException(400, "No API key configured (see README). The offline demo still works.")
            if not inference.is_valid(body.strategy):
                raise HTTPException(400, f"Unknown inference strategy: {body.strategy}")
            if not body.offline:
                estimate = credits.check_run(db, body.model, body.seconds)
                if estimate["refusal"]:
                    raise HTTPException(409, estimate["refusal"])
            worker.run_task(body.task, model=body.model, seconds=body.seconds, offline=body.offline,
                            strategy=inference.parse(body.strategy).id,
                            targets=demo_motion if body.offline else None, label="Offline demo" if body.offline else "")
        return {"ok": True}

    @app.post("/api/stop")
    def stop():
        with controls_lock:
            if campaign_active():
                raise HTTPException(409, "Stop the active campaign from Test Suite.")
            dropped = worker.cancel_queued()
            worker.stop()
        return {"ok": True, "dropped": dropped}

    @app.post("/api/reset")
    def reset():
        nonlocal reset_job
        def reset_scene(env):
            recorder.save(env)  # an open episode is kept, marked by the success check, before the scene resets
            try:
                env.reset()
            except Exception:
                bus.log("Scene reset failed. Check the simulator state before the next run.", "error")
                raise
            bus.log("Scene reset.")

        with controls_lock:
            if not worker.ready.is_set() or worker.error:
                raise HTTPException(503, "The simulator is unavailable.")
            if campaign_active() or (reset_job is not None and not reset_job.done()):
                raise HTTPException(409, "A campaign or scene reset is already active.")
            worker.cancel_queued()
            worker.stop()
            reset_job = worker.call(reset_scene)
        return {"ok": True}

    @app.post("/api/home")
    def home():
        with controls_lock:
            require_idle()
            worker.run_task("move arms home", offline=True, targets=lambda env: dsim.home_path(env.state()),
                            label="Home", stop_on_success=False)
        return {"ok": True}

    # ---------- Episodes (teaching loop) and the lab database ----------

    @app.get("/api/episodes")
    def episodes():
        return {
            "status": recorder.status(),
            "summary": db.summary(),
            "episodes": db.query(
                "SELECT id, task, model, took_over, seconds, dream_success, success, finetune_id, note, started_at "
                "FROM episodes WHERE status = 'saved' ORDER BY id DESC LIMIT 30"),
            "finetunes": db.query("SELECT id, name, task, episodes, frames, status, model_id, created_at "
                                  "FROM finetunes ORDER BY id DESC LIMIT 10"),
            "rules": scene.describe_rules(),
        }

    @app.post("/api/episodes/take-over")
    def take_over():
        try:
            return {"ok": True, "state": recorder.take_over(worker)}
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    @app.post("/api/episodes/save")
    def save_episode():
        if recorder.mode in (None, "dream"):
            raise HTTPException(409, "No episode to save. While Dream-1 works, press Take over or Stop first.")
        return {"ok": True, "episode": worker.call(recorder.save).result(timeout=120)}

    @app.post("/api/episodes/discard")
    def discard_episode():
        if recorder.mode in (None, "dream"):
            raise HTTPException(409, "No episode to discard. While Dream-1 works, press Take over or Stop first.")
        worker.call(recorder.discard).result(timeout=60)
        return {"ok": True}

    @app.post("/api/episodes/record")
    def record(body: RecordBody):
        recorder.enabled = body.enabled
        bus.emit("episode.state", recorder.status())
        return recorder.status()

    @app.post("/api/episodes/export")
    def export(body: ExportBody):
        try:
            result = export_episodes(db, body.task, body.name)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        try:
            used = db.query("SELECT id, seconds, took_over FROM episodes WHERE finetune_id = ? ORDER BY id",
                            (result["id"],))
            brain.export_done(result, body.task, used)
        except Exception as error:
            bus.log(f"Second brain: {error}", "warn")
        return result

    # ---------- Credits ----------

    @app.get("/api/credits")
    def credits_summary():
        return credits.summary(db)

    @app.get("/api/credits/estimate")
    def credits_estimate(model: str = dsim.BETA_MODEL, seconds: float = 60):
        return credits.check_run(db, model, seconds)

    @app.post("/api/credits/settings")
    def credits_settings(body: CreditSettingsBody):
        try:
            return credits.save_settings(db, **body.model_dump())
        except ValueError as error:
            raise HTTPException(400, str(error)) from None

    # ---------- Players (multiplayer) ----------

    @app.post("/api/join")
    def join(body: JoinBody, request: Request):
        ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")
        try:
            token, _ = players.join(ip, body.code, body.name)
        except PlayerError as error:
            raise HTTPException(error.status, str(error)) from None
        response = JSONResponse({"ok": True})
        response.set_cookie("dream_guest", token, httponly=True, samesite="lax", secure=is_remote(request.headers),
                            max_age=12 * 3600)
        return response

    @app.get("/api/players")
    def players_state(request: Request):
        return players.state(request.state.client, request.state.role)

    def player_call(fn, *args):
        try:
            fn(*args)
        except PlayerError as error:
            raise HTTPException(error.status, str(error)) from None

    @app.post("/api/players/claim")
    def claim(body: SideBody, request: Request):
        if body.side is None:
            raise HTTPException(400, "Say which arm: left or right.")
        player_call(players.claim, request.state.client, body.side, request.state.role)
        return players.state(request.state.client, request.state.role)

    @app.post("/api/players/release")
    def release(body: SideBody, request: Request):
        player_call(players.release, request.state.client, body.side, request.state.role)
        return players.state(request.state.client, request.state.role)

    @app.post("/api/players/name")
    def rename(body: NameBody, request: Request):
        players.rename(request.state.client, body.name)
        return players.state(request.state.client, request.state.role)

    @app.post("/api/players/tunnel")
    def tunnel(body: TunnelBody, request: Request):
        if body.open:
            player_call(players.tunnel.start, request.url.port or 8000)
        else:
            players.tunnel.stop()
        return players.state(request.state.client, request.state.role)

    @app.get("/api/players/tunnel")
    def tunnel_log():
        return {"status": players.tunnel.status(), "lines": players.tunnel.lines}

    @app.post("/api/camera")
    def camera(body: CameraBody):
        if body.reset:
            return worker.camera.reset()
        return worker.camera.update(**body.model_dump(exclude={"reset"}))

    # ---------- Video ----------

    @app.get("/snapshot/{name}.jpg")
    def snapshot(name: str):
        frame = worker.frames.get(name)
        if not frame:
            raise HTTPException(404)
        return Response(frame[1], media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get("/stream/{name}.mjpg")
    async def stream(name: str, request: Request):
        if name not in ("main", "main-teleop") and name.removesuffix("-large") not in CAMERAS:
            raise HTTPException(404)
        guest_main = is_remote(request.headers) and name == "main"  # guests get the smaller main view
        source = "main-low" if guest_main else name
        pause = 1 / 12 if is_remote(request.headers) else 1 / (MAIN_FPS + 5)

        async def frames():
            teleop = name == "main-teleop"
            last = worker.frames.get(name, (-1,))[0] if teleop else -1
            if teleop:
                worker.teleop_viewers += 1
            if guest_main:
                worker.low_viewers += 1
            try:
                while not closing.is_set():
                    frame = worker.frames.get(source)
                    if frame and frame[0] != last:
                        last = frame[0]
                        yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n%s\r\n" % (
                            len(frame[1]), frame[1])
                    await asyncio.sleep(pause)
            finally:
                if teleop:
                    worker.teleop_viewers -= 1
                if guest_main:
                    worker.low_viewers -= 1

        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                                 headers={"Cache-Control": "no-store"})

    # ---------- events ----------

    @app.websocket("/ws")
    async def websocket(ws: WebSocket):
        remote = is_remote(ws.headers)
        if remote and players.guest_client(ws.cookies.get("dream_guest")) is None:
            await ws.close(code=4401)
            return
        await ws.accept()
        queue = bus.subscribe()
        for message in list(bus.history):
            await ws.send_text(message)

        async def sender():
            while True:
                await ws.send_text(await queue.get())

        async def receiver():
            while True:
                message = await ws.receive_json()
                if message.get("type") == "camera" and not remote:  # the 3D view is shared: guests do not turn it
                    worker.camera.update(**{k: message.get(k) for k in ("lookat", "distance", "azimuth", "elevation")})

        tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        except WebSocketDisconnect:
            pass
        finally:
            for task in tasks:
                task.cancel()
            bus.unsubscribe(queue)

    # ---------- Extensions ----------

    for ext in extensions:
        try:
            router = ext.router()
            if router is not None:
                app.include_router(router, prefix=f"/api/ext/{ext.id}", tags=[ext.id])
        except Exception as error:
            bus.log(f"Router of {ext.id} failed: {error}", "error", ext.id)

    return app
