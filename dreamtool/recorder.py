"""Nimmt die Simulator-Kameras als MP4 auf, z. B. fuer das Demo-Video."""

from __future__ import annotations

from pathlib import Path

import av
import numpy as np


class VideoRecorder:
    """Schreibt RGB-Frames (H x W x 3, uint8) in eine MP4-Datei.

    Standard: die drei Kameras nebeneinander (top | left | right).
    """

    def __init__(self, path: str | Path, fps: int = 20, cameras=("top", "left", "right")):
        self.path = Path(path)
        self.fps = fps
        self.cameras = cameras
        self._container = None
        self._stream = None
        self.frames = 0

    def add(self, images: dict[str, np.ndarray]) -> None:
        frame = np.concatenate([images[name] for name in self.cameras], axis=1)
        if self._container is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._container = av.open(str(self.path), mode="w")
            codec = "libx264" if "libx264" in av.codecs_available else "mpeg4"
            self._stream = self._container.add_stream(codec, rate=self.fps)
            self._stream.width = frame.shape[1] - frame.shape[1] % 2
            self._stream.height = frame.shape[0] - frame.shape[0] % 2
            self._stream.pix_fmt = "yuv420p"
        frame = frame[: self._stream.height, : self._stream.width]
        for packet in self._stream.encode(av.VideoFrame.from_ndarray(np.ascontiguousarray(frame), format="rgb24")):
            self._container.mux(packet)
        self.frames += 1

    def close(self) -> None:
        if self._container is not None:
            for packet in self._stream.encode():
                self._container.mux(packet)
            self._container.close()
            self._container = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
