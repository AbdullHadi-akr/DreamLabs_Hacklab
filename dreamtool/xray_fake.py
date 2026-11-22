"""A stand-in for Dream-1 for tests and for trying the X-Ray without credits (DREAM_XRAY_FAKE=1).

It is NOT a model: it looks at one fixed patch of the overhead image (where the fruit lies) and at the object word in
the prompt, and turns the right arm accordingly. So the X-Ray has something to find: the overhead camera matters, the
wrist cameras do not, and the plan follows the word.
"""

from __future__ import annotations

import numpy as np

from . import xray

TURN = {"apple": 0.35, "banana": -0.35, "orange": 0.15, "bottle": 0.55}  # joint-1 turn per named object


class FakeDream:
    def __init__(self):
        self.frames, self.obs = {}, {}

    def reset_episode(self):
        self.frames, self.obs = {}, {}

    def set_observation(self, frames, observation, *, timestamp=None):
        self.frames, self.obs = dict(frames), dict(observation)

    def _joints(self, side):
        for key in (f"state.arm_{side[0]}.joint_pos", f"state.{side}_arm"):
            if key in self.obs:
                return np.asarray(self.obs[key], float)
        return np.zeros(6)

    def get_action(self):
        top = next((v for k, v in self.frames.items() if "overhead" in k or k.endswith(".top")), None)
        # how much structure the fruit patch shows (a blanked or masked patch has less): independent of the scene's colours
        patch = 0.5 if top is None else min(1.0, float(xray.decode_frame(top)[50:130, 110:210].std()) / 40)
        prompt = str(self.obs.get("prompt", "")).lower()
        turn = next((t for word, t in TURN.items() if word in prompt), -0.35)  # unknown word: the banana
        t = np.linspace(0, 1, 48)[:, None]
        right = np.hstack([np.tile(self._joints("right"), (48, 1)), np.ones((48, 1))])
        right[:, 0] += turn * t[:, 0] * (0.5 + patch)
        right[:, 1] += 0.4 * t[:, 0] * patch
        right[30:, 6] = 0.0
        left = np.hstack([np.tile(self._joints("left"), (48, 1)), np.ones((48, 1))])
        return {"q_l_chunk": left, "q_r_chunk": right}

    def close(self):
        pass


def open_fake(model):
    return FakeDream(), True
