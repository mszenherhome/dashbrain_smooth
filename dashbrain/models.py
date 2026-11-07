from __future__ import annotations

import time
from dataclasses import asdict, dataclass

@dataclass
class SensorState:
    updated_at: float = 0.0

    prox_left: int = 0
    prox_right: int = 0
    prox_rear: int = 0

    yaw: int = 0
    yaw_delta: int = 0
    pitch_delta: int = 0
    roll_delta: int = 0

    left_wheel: int = 0
    right_wheel: int = 0
    wheel_distance: int = 0

    head_pitch: int = 0
    head_yaw: int = 0

    pitch: int = 0
    roll: int = 0
    acceleration: int = 0

    button_main: bool = False
    button_1: bool = False
    button_2: bool = False
    button_3: bool = False

    moving: bool = False
    picked_up: bool = False
    hit: bool = False
    on_side: bool = False
    nominal: bool = True

    clap: bool = False
    mic_level: int = 0
    sound_direction: int = 0

    def age_s(self) -> float:
        if not self.updated_at:
            return 1e9
        return max(0.0, time.monotonic() - self.updated_at)

    def snapshot(self) -> dict:
        d = asdict(self)
        d["sensor_age_s"] = self.age_s()
        return d
