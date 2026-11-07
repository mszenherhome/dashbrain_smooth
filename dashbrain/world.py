from __future__ import annotations

import collections
import threading
import time
from typing import Any

class WorldModel:
    def __init__(self):
        self._lock = threading.RLock()
        self.sensors: dict[str, Any] = {}
        self.facts: dict[str, Any] = {
            "mode": "explore",
            "directive": "Explore safely, smoothly, and curiously.",
            "last_human_answer": None,
            "last_motor_kind": "stop",
            "commanded_linear": 0.0,
            "commanded_angular": 0.0,
            "desired_turn": 0.0,
        }
        self.events = collections.deque(maxlen=100)
        self.actions = collections.deque(maxlen=40)

    def update_sensors(self, snapshot: dict[str, Any]):
        with self._lock:
            self.sensors = dict(snapshot)

    def sensor(self, key: str, default=None):
        with self._lock:
            return self.sensors.get(key, default)

    def fact(self, key: str, default=None):
        with self._lock:
            return self.facts.get(key, default)

    def set_fact(self, key: str, value: Any):
        with self._lock:
            self.facts[key] = value

    def add_event(self, name: str, data=None, source: str = "system"):
        with self._lock:
            self.events.append({
                "time": time.time(),
                "name": name,
                "data": data,
                "source": source,
            })

    def recent_events(self, limit: int = 12):
        with self._lock:
            return list(self.events)[-limit:]

    def record_action(self, action: dict):
        with self._lock:
            self.actions.append({"time": time.time(), **action})

    def summary(self) -> dict:
        with self._lock:
            s = self.sensors
            return {
                "sensors": {
                    "prox_left": s.get("prox_left"),
                    "prox_right": s.get("prox_right"),
                    "prox_rear": s.get("prox_rear"),
                    "yaw": s.get("yaw"),
                    "wheel_distance": s.get("wheel_distance"),
                    "head_yaw": s.get("head_yaw"),
                    "head_pitch": s.get("head_pitch"),
                    "picked_up": s.get("picked_up"),
                    "hit": s.get("hit"),
                    "on_side": s.get("on_side"),
                    "clap": s.get("clap"),
                    "mic_level": s.get("mic_level"),
                    "sound_direction": s.get("sound_direction"),
                    "sensor_age_s": s.get("sensor_age_s"),
                },
                "facts": dict(self.facts),
                "recent_events": list(self.events)[-12:],
                "recent_actions": list(self.actions)[-12:],
            }
