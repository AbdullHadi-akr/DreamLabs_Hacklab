"""Extension-API (dieses Modul) + Loader. Jede Extension ist ein Ordner in dashboard/extensions/<name>/:

    __init__.py   Python: eine Unterklasse von `Extension` (Backend: API, Run-Hooks, 3D-Overlays)
    panel.js      optional, Browser: `export function mount(root, api)` rendert das Panel im Dashboard
    panel.css     optional, wird automatisch geladen

Ordner, die mit "_" beginnen (z. B. _template), werden nicht geladen. Neue Extension = _template kopieren.
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
    """Alles, was eine Extension von der App braucht."""

    def __init__(self, ext_id: str, sim, bus):
        self.id = ext_id
        self.sim = sim  # SimWorker: call(fn), run_task(task, ...), stop(), busy, status(), state_snapshot
        self.bus = bus

    def emit(self, event: str, data=None, *, keep: bool = True) -> None:
        """Event an alle Browser senden. Kommt im Panel an als api.on("<event>", fn)."""
        self.bus.emit(f"ext.{self.id}.{event}", data, keep=keep)

    def log(self, message: str, level: str = "info") -> None:
        self.bus.log(message, level, self.id)

    @property
    def data_dir(self) -> Path:
        """Ordner fuer Ergebnisse/Dateien dieser Extension (out/extensions/<id>/)."""
        path = DATA_DIR / self.id
        path.mkdir(parents=True, exist_ok=True)
        return path


class Extension:
    """Basisklasse. Ueberschreibe nur, was du brauchst."""

    id: str = ""  # eindeutig, URL-tauglich; Standard: Ordnername
    title: str = ""
    icon: str = "🧩"
    description: str = ""
    slot: str = "left"  # "left" = Tab in der linken Spalte, "right" = Karte in der rechten Spalte
    order: int = 100  # Sortierung (klein = weiter vorne)

    def __init__(self, ctx: ExtensionContext):
        self.ctx = ctx

    def setup(self) -> None:
        """Einmal nach dem Laden."""

    def router(self) -> APIRouter | None:
        """Eigene HTTP-API, erreichbar unter /api/ext/<id>/..."""
        return None

    def run_hooks(self, run: dict) -> Hooks | None:
        """Wird fuer JEDEN Lauf aufgerufen (auch die anderer Extensions). `run`: id, task, model, source, ..."""
        return None

    def decorate(self, env, scene: mujoco.MjvScene) -> None:
        """Vor jedem Frame der Hauptansicht: eigene 3D-Marker zeichnen (siehe overlay_*-Helfer unten)."""

    def shutdown(self) -> None:
        """Beim Beenden der App."""


def load_extensions(sim, bus) -> list[Extension]:
    """Alle Extensions finden und laden. Eine kaputte Extension wird geloggt und uebersprungen."""
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


# ---------- 3D-Overlay-Helfer fuer Extension.decorate() ----------

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
    """Flacher Zylinder, z. B. als Zielzone auf dem Tisch."""
    _add_geom(scene, mujoco.mjtGeom.mjGEOM_CYLINDER, (radius, height, 0), pos, rgba)


def overlay_line(scene, start, end, width=3.0, rgba=(0.3, 0.6, 1, 0.9)):
    if scene.ngeom >= scene.maxgeom:
        return
    geom = scene.geoms[scene.ngeom]
    mujoco.mjv_initGeom(geom, mujoco.mjtGeom.mjGEOM_LINE, np.zeros(3), np.zeros(3), _IDENTITY,
                        np.asarray(rgba, np.float32))
    mujoco.mjv_connector(geom, mujoco.mjtGeom.mjGEOM_LINE, width, np.asarray(start, float), np.asarray(end, float))
    scene.ngeom += 1
