"""FastAPI app: HTTP API, video streams (MJPEG), WebSocket events, extension routes."""

from __future__ import annotations

import asyncio
import contextlib
import mimetypes
import threading
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints

from dreamtool import sim as dsim

from .events import EventBus
from .extension import describe, load_extensions
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
]
EXT_FILE_TYPES = {".js", ".css", ".html", ".svg", ".png", ".jpg", ".json"}


class RunBody(BaseModel):
    task: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=300)]
    model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)] = dsim.BETA_MODEL
    seconds: float = Field(60, gt=0, le=3600)
    offline: bool = False


class CameraBody(BaseModel):
    lookat: list[float] | None = None
    distance: float | None = None
    azimuth: float | None = None
    elevation: float | None = None
    reset: bool = False


def create_app() -> FastAPI:
    bus = EventBus()
    worker = SimWorker(bus)
    extensions = load_extensions(worker, bus)
    worker.extensions = extensions
    campaigns = getattr(worker, "campaign_recovery", None)
    controls_lock = campaigns.lock if campaigns else threading.RLock()

    def campaign_active():
        return campaigns is not None and campaigns.active is not None

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        bus.bind(asyncio.get_running_loop())
        worker.start()
        await asyncio.get_running_loop().run_in_executor(None, worker.ready.wait, 60)
        yield
        for ext in extensions:
            with contextlib.suppress(Exception):
                ext.shutdown()
        worker.shutdown()
        await asyncio.get_running_loop().run_in_executor(None, worker.join, 5)

    app = FastAPI(title="Dream-1 Dashboard", lifespan=lifespan)
    app.state.bus, app.state.sim, app.state.extensions = bus, worker, extensions
    ## Set by the server on Ctrl+C (see __main__.py): ends the endless video streams, otherwise shutdown waits forever.
    app.state.closing = closing = threading.Event()

    @app.middleware("http")
    async def no_cache(request, call_next):
        """While developing: edited JS/CSS files show up immediately after a reload."""
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    # ---------- pages & files ----------

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
    def state():
        config = dsim.settings()
        return {
            "has_api_key": bool(config.get("DREAM_API_KEY")),
            "default_model": dsim.BETA_MODEL,
            "tasks": TASK_SUGGESTIONS,
            "cameras": list(CAMERAS),
            "camera": worker.camera.get(),
            "status": worker.status(),
            "sim": worker.state_snapshot,
            "extensions": [describe(e) for e in extensions],
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
            worker.run_task(body.task, model=body.model, seconds=body.seconds, offline=body.offline,
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
    async def stream(name: str):
        if name not in ("main", "main-teleop") and name not in CAMERAS:
            raise HTTPException(404)

        async def frames():
            teleop = name == "main-teleop"
            last = worker.frames.get(name, (-1,))[0] if teleop else -1
            if teleop:
                worker.teleop_viewers += 1
            try:
                while not closing.is_set():
                    frame = worker.frames.get(name)
                    if frame and frame[0] != last:
                        last = frame[0]
                        yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n%s\r\n" % (
                            len(frame[1]), frame[1])
                    await asyncio.sleep(1 / (MAIN_FPS + 5))
            finally:
                if teleop:
                    worker.teleop_viewers -= 1

        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                                 headers={"Cache-Control": "no-store"})

    # ---------- events ----------

    @app.websocket("/ws")
    async def websocket(ws: WebSocket):
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
                if message.get("type") == "camera":
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
