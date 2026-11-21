"""Zugriff auf den Dream YAM Simulator (examples/yam_mujoco aus dem dreamlabs-Repo).

Das Beispiel ist kein installiertes Python-Paket, sondern ein Ordner mit Skripten. Dieses Modul findet den Ordner,
haengt ihn an sys.path und re-exportiert die Teile, die wir brauchen: YamEnv (Physik + Kameras) und die
Request-Helfer aus dream_control (Beobachtung bauen, Frames fuettern, Action-Chunks pruefen).
"""

from __future__ import annotations

import os
import sys
import sysconfig
from pathlib import Path

## Hacklab/ (der Ordner, in dem dream-tool/ und dreamlabs/ nebeneinander liegen)
WORKSPACE = Path(__file__).resolve().parents[2]


def find_sim_dir() -> Path:
    """Ordner des yam_mujoco-Beispiels: $DREAM_SIM_DIR, sonst der Repo-Klon daneben, sonst die Kopie im Wheel."""
    candidates = []
    if os.environ.get("DREAM_SIM_DIR"):
        candidates.append(Path(os.environ["DREAM_SIM_DIR"]))
    candidates.append(WORKSPACE / "dreamlabs" / "dream_library" / "examples" / "yam_mujoco")
    candidates.append(Path(sysconfig.get_paths()["purelib"]) / "dream_examples" / "yam_mujoco")
    for path in candidates:
        if (path / "yam_env.py").is_file():
            return path
    raise FileNotFoundError(
        "Dream YAM Sim nicht gefunden. Klone github.com/dreamlabs-co/dreamlabs neben dream-tool/ "
        "oder setze DREAM_SIM_DIR auf .../dream_library/examples/yam_mujoco."
    )


SIM_DIR = find_sim_dir()
if str(SIM_DIR) not in sys.path:
    sys.path.insert(0, str(SIM_DIR))

import dream_control  # noqa: E402
import yam_env  # noqa: E402

YamEnv = yam_env.YamEnv
HOME = yam_env.HOME
home_path = yam_env.home_path
aim_viewer = yam_env.aim_viewer

BETA_MODEL = dream_control.BETA_MODEL
POSE_MODELS = dream_control.POSE_MODELS
VIDEO_ROLES = dream_control.VIDEO_ROLES
FRAMES = dream_control.FRAMES
FRAME_EVERY_STEPS = dream_control.FRAME_EVERY_STEPS

settings = dream_control.settings
resolve_model = dream_control.resolve_model
policy_config = dream_control.policy_config
open_policy = dream_control.open_policy
capture = dream_control.capture
feed = dream_control.feed
observation = dream_control.observation
validate_chunk = dream_control.validate_chunk
needs_poses = dream_control.needs_poses

__all__ = [name for name in dir() if not name.startswith("_") and name not in ("os", "sys", "sysconfig", "Path")]
