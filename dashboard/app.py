"""FastAPI app: HTTP API, video streams (MJPEG), WebSocket events, extension routes."""

from __future__ import annotations

import asyncio
import contextlib
import mimetypes
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from dreamtool import sim as dsim

from .episodes import Recorder
from .episodes import export as export_episodes
from .events import EventBus
from .extension import describe, load_extensions
from .lab_db import LabDB
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
    task: str = Field(min_length=2, max_length=300)
    model: str = dsim.BETA_MODEL
    seconds: float = Field(60, gt=0, le=3600)
    offline: bool = False


class RecordBody(BaseModel):
    enabled: bool


class ExportBody(BaseModel):
    task: str = Field(min_length=2, max_length=300)
    name: str = Field(pattern=r"^[a-z0-9-]{1,64}$")


class CameraBody(BaseModel):
    lookat: list[float] | None = None
    distance: float | None = None
    azimuth: float | None = None
    elevation: float | None = None
    reset: bool = False


def create_app() -> FastAPI:
    bus = EventBus()
    db = LabDB()
    recorder = Recorder(db, bus)
    worker = SimWorker(bus, db=db, recorder=recorder)
    extensions = load_extensions(worker, bus)
    worker.extensions = extensions

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
    app.state.db, app.state.recorder = db, recorder

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
            "episode": recorder.status(),
        }

    def require_idle():
        if worker.busy:
            raise HTTPException(409, "A run is already active (or queued). Stop it first.")

    @app.post("/api/run")
    def run(body: RunBody):
        require_idle()
        if not body.offline and not dsim.settings().get("DREAM_API_KEY"):
            raise HTTPException(400, "No API key configured (see README). The offline demo still works.")
        worker.run_task(body.task, model=body.model, seconds=body.seconds, offline=body.offline,
                        targets=demo_motion if body.offline else None, label="Offline demo" if body.offline else "")
        return {"ok": True}

    @app.post("/api/stop")
    def stop():
        dropped = worker.cancel_queued()
        worker.stop()
        return {"ok": True, "dropped": dropped}

    @app.post("/api/reset")
    def reset():
        worker.cancel_queued()
        worker.stop()
        worker.call(recorder.save)  # an open episode is kept, marked by the success check, before the scene resets
        worker.call(lambda env: env.reset())
        bus.log("Scene reset.")
        return {"ok": True}

    @app.post("/api/home")
    def home():
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
            return export_episodes(db, body.task, body.name)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None

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
        if name != "main" and name.removesuffix("-large") not in CAMERAS:
            raise HTTPException(404)

        async def frames():
            last = -1
            while True:
                frame = worker.frames.get(name)
                if frame and frame[0] != last:
                    last = frame[0]
                    yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n%s\r\n" % (
                        len(frame[1]), frame[1])
                await asyncio.sleep(1 / (MAIN_FPS + 5))

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
