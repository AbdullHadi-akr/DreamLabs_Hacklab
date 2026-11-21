"""Evaluate supported placement tasks from MuJoCo poses and contact pairs."""

import re
import numpy as np

from dreamtool import scene

STABILITY_SECONDS = 0.4


def placement_failure(evidence, termination):
    """One diagnostic for the stored category, inspector and campaign summary."""
    if evidence.get("entered_target_region") or evidence.get("in_target_region"):
        if not evidence.get("in_target_region"):
            return "UNSTABLE_PLACEMENT", "The object entered the target region and subsequently left it."
        if not evidence.get("released"):
            return "PLACEMENT_FAILED", "The object reached the target region while still in contact with the robot."
        if not evidence.get("supported_by_target"):
            return "PLACEMENT_FAILED", "The object entered the target region without being supported by the target."
        return "UNSTABLE_PLACEMENT", "A released placement did not meet the stability window."
    if evidence.get("gripper_contact_observed") and not evidence.get("picked_up"):
        contact = next((event["simulation_time"] for event in evidence.get("events", [])
                        if event["event"] == "Gripper contacted object"), None)
        observed = f" at {contact:.1f} s simulation time" if contact is not None else ""
        ending = (" The object remained outside the target region until the deadline."
                  if termination == "task_deadline" else "")
        return "PICKUP_FAILED", f"Pickup failed. Gripper contact was observed{observed}, but no successful lift was detected.{ending}"
    if evidence.get("picked_up"):
        if evidence.get("transported") or evidence.get("made_target_progress"):
            return "TARGET_NOT_REACHED", "The object was lifted and moved, but never entered the target region."
        return "TRANSPORT_FAILED", "The object was lifted, but no held transport or meaningful movement toward the target was observed."
    if evidence.get("grasp_attempt_observed"):
        return "GRASP_FAILED", "The gripper closed near the object without verified contact."
    distance = evidence.get("closest_gripper_distance_m")
    if distance is None:
        return "EVALUATION_UNAVAILABLE", "Gripper proximity and contact could not be established from the recorded telemetry."
    if distance <= .08:
        return "NO_GRASP_OBSERVED", "The gripper came within 8 cm of the object, with no verified contact or nearby gripper closure."
    return "OBJECT_NOT_REACHED", f"The closest gripper came within {distance * 100:.1f} cm of the object and made no verified contact."


def placement(text):
    """Recognize a single final placement goal, including 'banana on plate'."""
    normalized = " ".join(text.casefold().split()).rstrip(".!")
    normalized = re.sub(r"\bwater[ -]bottle\b", "water_bottle", normalized)
    match = re.fullmatch(
        r"(?:please,? )?(?:(?:put|place|move|set) )?(?:(?:the|an?) )?(\w+) "
        r"(?:on top of|into|inside|in|onto|on|to) (?:(?:the|an?) )?(\w+)(?:,? please)?",
        normalized,
    )
    if not match:
        return None
    obj, target = match.groups()
    if obj == "water":
        return None  # The simulator models the bottle; it has no liquid telemetry.
    return scene.parse_task(f"put {obj} in {target}")


def snapshot(env):
    return {
        "simulation_time": float(env.data.time),
        "positions_m": {name: value.tolist() for name, value in scene.positions(env).items()},
        "object_quaternions": {name: env.data.body(name).xquat.tolist() for name in scene.OBJECTS},
        "robot": {name: value.tolist() for name, value in env.state().items()},
    }


class Placement:
    def __init__(self, goal):
        self.goal = goal
        self.stable_since = None
        self.latest = None
        self.complete = False
        self.best_planar_distance = None
        self.entered_region = False
        self.longest_stable = 0.
        self.initial_distance = None
        self.initial_height = None
        self.picked_up = False
        self.released_after_pickup = False
        self.lost_candidate = False
        self.events = []
        self.closest_gripper = None
        self.gripper_contact = False
        self.last_progress_time = None
        self.transported = False
        self.pickup_position = None
        self.previous_opening = None
        self.grasp_attempt = False
        self.target_progress = False

    def prepare(self, env):
        if self.goal:
            obj, target = self.goal
            position = scene.position(env, obj)
            self.initial_height = float(position[2])
            self.initial_distance = float(np.linalg.norm((position - scene.position(env, target))[:2]))

    def sample(self, env, robot_state=None):
        if self.goal is None:
            return
        obj, target = self.goal
        if self.initial_distance is None:
            self.prepare(env)
        body = env.model.body(obj).id
        contacts = set()
        for i in range(env.data.ncon):
            contact = env.data.contact[i]
            if contact.efc_address < 0:
                continue
            a, b = (int(env.model.geom_bodyid[index]) for index in contact.geom)
            if a == body:
                contacts.add(env.model.body(b).name)
            if b == body:
                contacts.add(env.model.body(a).name)
        released = not any(name.startswith(("left_", "right_")) for name in contacts)
        supported = target in contacts
        in_region = scene.is_in(env, obj, target)
        relative = scene.position(env, obj) - scene.position(env, target)
        planar_distance = float(np.linalg.norm(relative[:2]))
        if self.best_planar_distance is None or planar_distance < self.best_planar_distance:
            self.best_planar_distance = planar_distance
        now = float(env.data.time)
        if not self.target_progress and self.initial_distance - self.best_planar_distance >= .02:
            self.target_progress = True
            self.events.append(dict(event="Object moved at least 2 cm closer to target", simulation_time=now))
        object_position = scene.position(env, obj)
        distances = {side: float(np.linalg.norm(env.data.site(f"{side}_tcp").xpos - object_position))
                     for side in ("left", "right")}
        gripper_distance = min(distances.values())
        self.closest_gripper = min(gripper_distance, self.closest_gripper if self.closest_gripper is not None else gripper_distance)
        if self.closest_gripper <= .08 and not any(event["event"] == "Gripper within 8 cm of object" for event in self.events):
            self.events.append(dict(event="Gripper within 8 cm of object", simulation_time=now))
        opening = {side: float(state[-1]) for side, state in (robot_state or env.state()).items()}
        if self.previous_opening and not self.grasp_attempt and any(
            distances[side] <= .08 and self.previous_opening[side] - opening[side] >= .04 for side in distances
        ):
            self.grasp_attempt = True
            self.events.append(dict(event="Gripper closed near the object", simulation_time=now))
        self.previous_opening = opening
        if in_region and not self.entered_region:
            self.events.append(dict(event="Entered target region", simulation_time=now))
            self.entered_region = True
        grasp_contact = any(name.startswith(("left_tip_", "right_tip_", "left_gripper", "right_gripper"))
                            for name in contacts)
        if grasp_contact and not self.gripper_contact:
            self.gripper_contact = True
            self.events.append(dict(event="Gripper contacted object", simulation_time=now))
        if not self.picked_up and grasp_contact and scene.position(env, obj)[2] > self.initial_height + .03:
            self.picked_up = True
            self.pickup_position = object_position
            self.events.append(dict(event="Lifted at least 3 cm with gripper contact", simulation_time=now))
        if self.picked_up and grasp_contact and not self.transported and np.linalg.norm(object_position[:2] - self.pickup_position[:2]) >= .02:
            self.transported = True
            self.events.append(dict(event="Transported object while in gripper contact", simulation_time=now))
        if self.picked_up and released and not self.released_after_pickup:
            self.released_after_pickup = True
            self.events.append(dict(event="Robot contact ended after pickup", simulation_time=now))
        velocity = env.data.joint(scene.FREE_JOINTS[obj]).qvel
        linear = float(np.linalg.norm(velocity[:3]))
        angular = float(np.linalg.norm(velocity[3:]))
        settled = in_region and supported and released and linear <= .04 and angular <= 1.
        if not settled:
            if self.stable_since is not None and not self.lost_candidate:
                self.lost_candidate = True
                self.events.append(dict(event="Lost a candidate placement before confirmation", simulation_time=now))
            self.stable_since = None
        elif self.stable_since is None:
            self.stable_since = now
        stable = now - self.stable_since if self.stable_since is not None else 0.
        self.longest_stable = max(self.longest_stable, stable)
        complete = stable + 1e-8 >= STABILITY_SECONDS
        if complete and not self.complete:
            self.events.append(dict(event="Stable placement confirmed", simulation_time=now))
        self.complete = complete
        self.last_progress_time = max((event["simulation_time"] for event in self.events
                                       if not event["event"].startswith("Lost")), default=None)
        self.latest = dict(object=obj, target=target, in_target_region=in_region,
                           supported_by_target=supported, released=released, contacts=sorted(contacts),
                           planar_distance_m=planar_distance, target_radius_m=scene.CONTAINER_SIZE[target][0],
                           best_planar_distance_m=self.best_planar_distance, height_above_target_m=float(relative[2]),
                           initial_planar_distance_m=self.initial_distance, picked_up=self.picked_up,
                           released_after_pickup=self.released_after_pickup, lost_candidate=self.lost_candidate,
                           made_target_progress=self.target_progress, stable_placement_observed=complete,
                           events=list(self.events),
                           entered_target_region=self.entered_region, longest_stable_seconds=self.longest_stable,
                           closest_gripper_distance_m=self.closest_gripper, gripper_contact_observed=self.gripper_contact,
                           grasp_attempt_observed=self.grasp_attempt,
                           transported=self.transported, last_progress_simulation_time=self.last_progress_time,
                           linear_speed_m_s=linear, angular_speed_rad_s=angular,
                           stable_seconds=stable, required_stable_seconds=STABILITY_SECONDS)

    def classify(self, termination, verdict, api_failed=False):
        if verdict is True:
            return None, "Stable placement"
        evidence = self.latest or {}
        stage = next((label for key, label in (
            ("entered_target_region", "Target entry"), ("released_after_pickup", "Release"),
            ("transported", "Transportation"), ("picked_up", "Pickup"), ("gripper_contact_observed", "Gripper contact"),
            ("grasp_attempt_observed", "Grasp attempt"),
        ) if evidence.get(key)), None)
        if stage is None and self.closest_gripper is not None and self.closest_gripper <= .08:
            stage = "Object approach"
        if termination.startswith("error") or termination == "api_timeout":
            return ("API_ERROR" if api_failed or termination == "api_timeout" else "SIMULATION_ERROR"), stage
        if termination in ("stopped", "interrupted"):
            return None, stage
        if termination in ("agent_idle", "repeated_ineffective_actions"):
            return "ROBOT_STALLED", stage
        if self.goal and evidence:
            return placement_failure(evidence, termination)[0], stage
        return "EVALUATION_UNAVAILABLE", stage

    def result(self, termination, offline):
        if offline:
            return None, "Dry run exercised setup and telemetry without running Dream-1."
        if termination in ("task_completed", "success") and self.complete:
            return True, None
        if termination not in ("task_deadline", "request_budget", "agent_idle", "repeated_ineffective_actions", "task_finished"):
            return None, f"Execution ended before a verdict: {termination}."
        if self.goal is None:
            return None, "No supported automatic criterion. Set an explicit object placement goal."
        if not self.latest:
            return None, "No task-controlled simulation steps were observed."
        stable_candidate = all(self.latest[key] for key in ("in_target_region", "supported_by_target", "released"))
        reason = placement_failure(self.latest, termination)[1]
        if termination in ("agent_idle", "repeated_ineffective_actions"):
            reason = f"Robot stalled. {reason}"
        return (None if stable_candidate else False), reason
