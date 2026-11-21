"""Collect a bounded set of run observations from existing simulator callbacks."""


class RunTelemetry:
    def __init__(self):
        self.samples = []
        self.last_sample = None
        self.closest = None
        self.frames = {}
        self.closest_frame_distance = None
        self.milestones = {}

    def observe(self, time, distance, events, overhead):
        if distance is not None:
            self.last_sample = [time, distance]
            if not self.samples or time - self.samples[-1][0] >= .2 - 1e-8:
                self.samples.append(self.last_sample)
            if self.closest is None or distance < self.closest[1]:
                self.closest = self.last_sample

        for event in events:
            name = event["event"]
            if name.startswith("Lifted"):
                self.milestones.setdefault("pickup", event)
            elif name == "Gripper contacted object":
                self.milestones.setdefault("contact", event)

        if overhead is None:
            return
        frame = (time, overhead.copy())
        self.frames.setdefault("first", frame)
        self.frames["final"] = frame
        if distance is not None and (self.closest_frame_distance is None or distance < self.closest_frame_distance):
            self.closest_frame_distance = distance
            self.frames["closest"] = frame
        for key in self.milestones:
            self.frames.setdefault(key, frame)

    def progress(self, events, termination, final_time):
        if not self.samples:
            return None
        markers = [dict(event) for event in events if event["event"].startswith(
            ("Lifted", "Robot contact ended", "Entered target", "Stable placement confirmed"))]
        markers.append(dict(event="Closest measured approach", simulation_time=self.closest[0], distance_m=self.closest[1]))
        if final_time is not None and termination not in ("task_completed", "success"):
            markers.append(dict(event="Run ended", simulation_time=final_time, termination=termination))
        markers.sort(key=lambda marker: marker["simulation_time"])
        # Include the measured minimum and last point even between sampling intervals.
        points = {time: distance for time, distance in [*self.samples, self.last_sample, self.closest]}
        return dict(samples=sorted(points.items()), markers=markers)
