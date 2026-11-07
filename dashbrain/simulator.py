from __future__ import annotations

import time

from .models import SensorState

class SimulatedDash:
    """Small simulator for testing orchestration without the real robot."""

    def __init__(self):
        self.state = SensorState(updated_at=time.monotonic())
        self.connected = False
        self._motion_until = 0.0
        self._continuous_linear = 0.0
        self._continuous_angular = 0.0
        self._last_tick = time.monotonic()

    @property
    def motion_active(self):
        return (
            time.monotonic() < self._motion_until
            or abs(self._continuous_linear) > 1e-6
            or abs(self._continuous_angular) > 1e-6
        )

    @property
    def bounded_motion_active(self):
        return time.monotonic() < self._motion_until

    async def connect(self):
        self.connected = True
        self.state.updated_at = time.monotonic()
        return self

    async def disconnect(self):
        self.connected = False

    async def stop(self):
        self._motion_until = 0.0
        self._continuous_linear = 0.0
        self._continuous_angular = 0.0
        self.state.moving = False

    async def set_velocity(self, linear: float, angular: float):
        self._motion_until = 0.0
        self._continuous_linear = max(-1.0, min(1.0, float(linear)))
        self._continuous_angular = max(-1.0, min(1.0, float(angular)))
        self.state.moving = (
            abs(self._continuous_linear) > 1e-6
            or abs(self._continuous_angular) > 1e-6
        )

    async def move_bounded(self, distance_mm: int, duration_ms: int = 200):
        await self.stop()
        self._motion_until = time.monotonic() + duration_ms / 1000.0
        self.state.moving = True
        self.state.left_wheel += distance_mm
        self.state.right_wheel += distance_mm
        self.state.wheel_distance += distance_mm
        self.state.updated_at = time.monotonic()

    async def turn_bounded(self, degrees: float, duration_ms: int = 200):
        await self.stop()
        self._motion_until = time.monotonic() + duration_ms / 1000.0
        self.state.moving = True
        self.state.yaw += int(degrees)
        self.state.yaw_delta = int(degrees)
        self.state.updated_at = time.monotonic()

    async def head_yaw(self, degrees: int):
        self.state.head_yaw = int(degrees)
        self.state.updated_at = time.monotonic()

    async def head_pitch(self, degrees: int):
        self.state.head_pitch = int(degrees)
        self.state.updated_at = time.monotonic()

    async def say(self, sound: str):
        print(f"[SIM SOUND] {sound}")

    def tick(self):
        now = time.monotonic()
        dt = max(0.0, min(0.2, now - self._last_tick))
        self._last_tick = now

        if now >= self._motion_until and self._motion_until != 0.0:
            self._motion_until = 0.0
            self.state.moving = False

        if abs(self._continuous_linear) > 1e-6:
            delta = int(self._continuous_linear * 70.0 * dt)
            self.state.left_wheel += delta
            self.state.right_wheel += delta
            self.state.wheel_distance += delta

        if abs(self._continuous_angular) > 1e-6:
            dyaw = int(self._continuous_angular * 60.0 * dt)
            self.state.yaw_delta = dyaw
            self.state.yaw += dyaw
        else:
            self.state.yaw_delta = 0

        self.state.moving = self.motion_active
        self.state.updated_at = now
