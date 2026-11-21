"""Extension API (this module) + loader. Every extension is a folder in dashboard/extensions/<name>/:

    __init__.py   Python: a subclass of `Extension` (backend: API, run hooks, 3D overlays)
    panel.js      optional, browser: `export function mount(root, api)` renders the panel in the dashboard
    panel.css     optional, loaded automatically

Folders starting with "_" (e.g. _template) are not loaded. New extension = copy _template.
"""

from __future__ import annotations

import importlib
import pkgutil
import traceback
from pathlib import Path

import mujoco
import numpy as np
from fastapi import APIRouter

from dreamtool.runner import Hooks

EXTENSIONS_DIR = Path(__file__).parent / "extensions"
DATA_DIR = Path(__file__).resolve().parents[1] / "out" / "extensions"


class ExtensionContext:
    """Everything an extension needs from the app."""

    def __init__(self, ext_id: str, sim, bus):
        self.id = ext_id
        self.sim = sim  # SimWorker: call(fn), run_task(task, ...), stop(), busy, status(), state_snapshot
        self.bus = bus

    def emit(self, event: str, data=None, *, keep: bool = True) -> None:
        """Send an event to all browsers. Arrives in the panel as api.on("<event>", fn)."""
        self.bus.emit(f"ext.{self.id}.{event}", data, keep=keep)

    def log(self, message: str, level: str = "info") -> None:
        self.bus.log(message, level, self.id)

    @property
    def data_dir(self) -> Path:
        """Folder for this extension's results/files (out/extensions/<id>/)."""
        path = DATA_DIR / self.id
        path.mkdir(parents=True, exist_ok=True)
        return path


class Extension:
    """Base class. Override only what you need."""

    id: str = ""  # unique, URL-safe; default: folder name
    title: str = ""
    icon: str = ""
    description: str = ""
    slot: str = "left"  # "left" = tab in the left column, "right" = card in the right column
    order: int = 100  # sort order (smaller = further up front)

    def __init__(self, ctx: ExtensionContext):
        self.ctx = ctx

    def setup(self) -> None:
        """Once after loading."""

    def router(self) -> APIRouter | None:
        """Your own HTTP API, served under /api/ext/<id>/..."""
        return None

    def run_hooks(self, run: dict) -> Hooks | None:
        """Called for EVERY run (including other extensions' runs). `run`: id, task, model, source, ..."""
        return None

    def decorate(self, env, scene: mujoco.MjvScene) -> None:
        """Before every frame of the main view: draw your own 3D markers (see the overlay_* helpers below)."""

    def shutdown(self) -> None:
        """When the app shuts down."""


def load_extensions(sim, bus) -> list[Extension]:
    """Find and load all extensions. A broken extension is logged and skipped."""
    loaded = []
    for info in pkgutil.iter_modules([str(EXTENSIONS_DIR)]):
        if info.name.startswith("_") or not info.ispkg:
            continue
        try:
            module = importlib.import_module(f"dashboard.extensions.{info.name}")
            classes = [
                obj for obj in vars(module).values()
                if isinstance(obj, type) and issubclass(obj, Extension) and obj is not Extension
                and obj.__module__ == module.__name__
            ]
            if not classes:
                raise TypeError("no Extension subclass found")
            cls = classes[0]
            ext_id = cls.id or info.name
            ext = cls(ExtensionContext(ext_id, sim, bus))
            ext.id = ext_id
            ext.title = ext.title or ext_id
            ext.folder = EXTENSIONS_DIR / info.name
            ext.setup()
            loaded.append(ext)
        except Exception:
            bus.log(f"Extension '{info.name}' not loaded:\n{traceback.format_exc()}", "error")
    loaded.sort(key=lambda e: (e.order, e.id))
    return loaded


def describe(ext: Extension) -> dict:
    return {
        "id": ext.id, "title": ext.title, "icon": ext.icon, "description": ext.description, "slot": ext.slot,
        "has_panel": (ext.folder / "panel.js").is_file(), "has_css": (ext.folder / "panel.css").is_file(),
    }


# ---------- 3D overlay helpers for Extension.decorate() ----------

_IDENTITY = np.eye(3).ravel()


def _add_geom(scene: mujoco.MjvScene, kind, size, pos, rgba, mat=_IDENTITY) -> None:
    if scene.ngeom >= scene.maxgeom:
        return
    geom = scene.geoms[scene.ngeom]
    mujoco.mjv_initGeom(geom, kind, np.asarray(size, float), np.asarray(pos, float), np.asarray(mat, float),
                        np.asarray(rgba, np.float32))
    geom.category = mujoco.mjtCatBit.mjCAT_DECOR
    scene.ngeom += 1


def overlay_sphere(scene, pos, radius=0.01, rgba=(1, 0.3, 0.2, 0.8)):
    _add_geom(scene, mujoco.mjtGeom.mjGEOM_SPHERE, (radius, 0, 0), pos, rgba)


def overlay_disk(scene, pos, radius=0.05, height=0.002, rgba=(0.2, 0.8, 0.4, 0.3)):
    """Flat cylinder, e.g. as a target zone on the table."""
    _add_geom(scene, mujoco.mjtGeom.mjGEOM_CYLINDER, (radius, height, 0), pos, rgba)


def overlay_line(scene, start, end, width=3.0, rgba=(0.3, 0.6, 1, 0.9)):
    if scene.ngeom >= scene.maxgeom:
        return
    geom = scene.geoms[scene.ngeom]
    mujoco.mjv_initGeom(geom, mujoco.mjtGeom.mjGEOM_LINE, np.zeros(3), np.zeros(3), _IDENTITY,
                        np.asarray(rgba, np.float32))
    mujoco.mjv_connector(geom, mujoco.mjtGeom.mjGEOM_LINE, width, np.asarray(start, float), np.asarray(end, float))
    scene.ngeom += 1
