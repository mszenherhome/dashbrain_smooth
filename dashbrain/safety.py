from __future__ import annotations

from typing import Any

class SafetyKernel:
    """
    Immutable safety layer.

    Generated skills never receive a reference to this object and cannot
    change its configuration directly.
    """

    def __init__(self, config: dict[str, Any]):
        self.cfg = config

    def immediate_hazard(self, sensors: dict) -> tuple[bool, str]:
        if sensors.get("sensor_age_s", 999) > float(self.cfg["sensor_stale_s"]):
            return True, "sensor stream stale"
        if sensors.get("picked_up"):
            return True, "robot picked up"
        if sensors.get("hit"):
            return True, "collision/bump event"
        if sensors.get("on_side"):
            return True, "robot on side"
        return False, ""

    def filter_velocity(self, intent: dict, sensors: dict) -> tuple[dict, str | None]:
        hazard, reason = self.immediate_hazard(sensors)
        if hazard:
            return {
                "type": "velocity",
                "linear": 0.0,
                "angular": 0.0,
                "priority": 1000,
            }, reason

        linear = max(-1.0, min(1.0, float(intent.get("linear", 0.0))))
        angular = max(-1.0, min(1.0, float(intent.get("angular", 0.0))))

        if linear != 0.0 and not self.cfg.get("proximity_calibrated", False):
            return {
                **intent,
                "linear": 0.0,
                "angular": angular,
            }, "proximity sensors are not marked calibrated"

        threshold = int(self.cfg["proximity_stop_threshold"])
        left = int(sensors.get("prox_left") or 0)
        right = int(sensors.get("prox_right") or 0)
        rear = int(sensors.get("prox_rear") or 0)

        if linear > 0 and (left >= threshold or right >= threshold):
            return {
                **intent,
                "linear": 0.0,
                "angular": angular,
            }, f"front obstacle L={left} R={right}"

        if linear < 0 and rear >= threshold:
            return {
                **intent,
                "linear": 0.0,
                "angular": angular,
            }, f"rear obstacle R={rear}"

        return {
            **intent,
            "linear": linear,
            "angular": angular,
        }, None

    def filter_motion(self, intent: dict, sensors: dict) -> tuple[dict, str | None]:
        hazard, reason = self.immediate_hazard(sensors)
        if hazard:
            return {"type": "motion", "kind": "stop", "priority": 1000}, reason

        kind = intent.get("kind", "stop")

        if kind in ("forward", "backward") and not self.cfg.get(
            "proximity_calibrated", False
        ):
            return (
                {"type": "motion", "kind": "stop", "priority": 1000},
                "proximity sensors are not marked calibrated",
            )

        threshold = int(self.cfg["proximity_stop_threshold"])
        left = int(sensors.get("prox_left") or 0)
        right = int(sensors.get("prox_right") or 0)
        rear = int(sensors.get("prox_rear") or 0)

        if kind == "forward" and (left >= threshold or right >= threshold):
            return (
                {"type": "motion", "kind": "stop", "priority": 1000},
                f"front obstacle L={left} R={right}",
            )

        if kind == "backward" and rear >= threshold:
            return (
                {"type": "motion", "kind": "stop", "priority": 1000},
                f"rear obstacle R={rear}",
            )

        out = dict(intent)
        out["duration_ms"] = min(
            int(out.get("duration_ms", 180)),
            int(self.cfg["max_motion_duration_ms"]),
        )

        if kind == "forward":
            out["amount"] = min(
                abs(int(out.get("amount", 25))),
                int(self.cfg["max_forward_mm"]),
            )
        elif kind == "backward":
            out["amount"] = min(
                abs(int(out.get("amount", 20))),
                int(self.cfg["max_reverse_mm"]),
            )
        elif kind in ("turn_left", "turn_right"):
            out["amount"] = min(
                abs(int(out.get("amount", 18))),
                int(self.cfg["max_turn_deg"]),
            )
        elif kind != "stop":
            return {"type": "motion", "kind": "stop", "priority": 1000}, "unknown motion"

        return out, None
