from __future__ import annotations

import asyncio
import math
import time
from typing import Optional

from bleak import BleakClient, BleakScanner

from .models import SensorState

SERVICE_UUID = "af237777-879d-6186-1f49-deca0e85d9c1"
COMMAND_UUID = "af230002-879d-6186-1f49-deca0e85d9c1"
DOT_SENSOR_UUID = "af230003-879d-6186-1f49-deca0e85d9c1"
DASH_SENSOR_UUID = "af230006-879d-6186-1f49-deca0e85d9c1"

CMD_DRIVE = 0x02
CMD_HEAD_YAW = 0x06
CMD_HEAD_PITCH = 0x07
CMD_SAY = 0x18
CMD_MOVE = 0x23

SOUNDS = {
    "hi": bytes.fromhex("53595354444153485f48495f564f0b00c900"),
    "ohno": bytes.fromhex("5359535456375f4f484e4f5f30390b000000"),
    "confused": bytes.fromhex("53595354434f4e46555345445f310b000000"),
    "charge": bytes.fromhex("535953544348415247455f3033000b000000"),
    "elephant": bytes.fromhex("53595354454c455048414e545f300e460000"),
}

def _signed(value: int, bits: int) -> int:
    if value > ((1 << (bits - 1)) - 1):
        return value - (1 << bits)
    return value

class DashBLE:
    """
    Python-3/Bleak Dash driver.

    It supports:
      * sensor notifications
      * continuous combined linear/angular velocity
      * bounded move/turn commands
      * head position
      * a small set of built-in sounds
    """

    def __init__(
        self,
        address: Optional[str] = None,
        max_linear_raw: int = 180,
        max_angular_raw: int = 160,
    ):
        self.address = address
        self.device = None
        self.client: Optional[BleakClient] = None
        self.state = SensorState()
        self._write_lock = asyncio.Lock()
        self._motion_until = 0.0
        self._continuous_linear = 0.0
        self._continuous_angular = 0.0
        self.max_linear_raw = int(max_linear_raw)
        self.max_angular_raw = int(max_angular_raw)

    @property
    def connected(self) -> bool:
        return bool(self.client and self.client.is_connected)

    @property
    def motion_active(self) -> bool:
        return (
            time.monotonic() < self._motion_until
            or abs(self._continuous_linear) > 1e-6
            or abs(self._continuous_angular) > 1e-6
        )

    @property
    def bounded_motion_active(self) -> bool:
        return time.monotonic() < self._motion_until

    async def discover(self, timeout: float = 15.0):
        if self.address:
            self.device = await BleakScanner.find_device_by_address(
                self.address, timeout=timeout
            )
        else:
            def is_dash(device, advertisement):
                uuids = [u.lower() for u in (advertisement.service_uuids or [])]
                name = (advertisement.local_name or device.name or "").lower()
                return SERVICE_UUID in uuids or "dash" in name

            self.device = await BleakScanner.find_device_by_filter(
                is_dash, timeout=timeout
            )

        if not self.device:
            raise RuntimeError(
                "Dash was not found. Make sure it is powered on and not "
                "connected to another controller."
            )
        return self.device

    async def connect(self):
        if not self.device:
            await self.discover()

        self.client = BleakClient(
            self.device,
            disconnected_callback=self._on_disconnect,
        )
        await self.client.connect()
        await self.client.start_notify(DOT_SENSOR_UUID, self._dot_sensor)
        await self.client.start_notify(DASH_SENSOR_UUID, self._dash_sensor)
        return self

    async def disconnect(self):
        if self.client and self.client.is_connected:
            try:
                await self.stop()
            finally:
                await self.client.disconnect()

    def _on_disconnect(self, _client):
        self._motion_until = 0.0
        self._continuous_linear = 0.0
        self._continuous_angular = 0.0
        print("[BLE] Dash disconnected")

    async def _command(self, opcode: int, payload: bytes = b""):
        if not self.connected:
            raise RuntimeError("Dash is not connected")
        async with self._write_lock:
            await self.client.write_gatt_char(
                COMMAND_UUID,
                bytes([opcode]) + payload,
                response=False,
            )

    def _dot_sensor(self, _characteristic, value: bytearray):
        if len(value) < 20:
            return
        s = self.state
        s.updated_at = time.monotonic()

        s.pitch = _signed(((value[4] & 0xF0) << 4) | value[2], 12)
        s.roll = _signed(((value[4] & 0x0F) << 8) | value[3], 12)
        s.acceleration = _signed(((value[5] & 0xF0) << 4) | value[6], 12)

        s.button_main = bool(value[8] & 0x10)
        s.button_1 = bool(value[8] & 0x20)
        s.button_2 = bool(value[8] & 0x40)
        s.button_3 = bool(value[8] & 0x80)

        flags = value[11]
        s.moving = flags == 0
        s.picked_up = bool(flags & 0x04)
        s.hit = bool(flags & 0x01)
        s.on_side = (flags & 0x20) == 0x20 and not ((flags & 0x30) == 0x30)
        s.nominal = (flags & 0x30) == 0x30

        # Community decoders expose microphone level and sound direction here.
        s.mic_level = int(value[7])
        if value[15] == 4:
            s.sound_direction = (value[13] << 8) | value[12]

        # Some community implementations reuse event bits for bump/clap-style
        # events. Treat this only as an event hint, not a safety-critical signal.
        s.clap = bool(flags & 0x01)

    def _dash_sensor(self, _characteristic, value: bytearray):
        if len(value) < 20:
            return
        s = self.state
        s.updated_at = time.monotonic()

        s.pitch_delta = _signed(((value[4] & 0x30) << 4) | value[3], 10)
        s.roll_delta = _signed(((value[4] & 0x03) << 8) | value[5], 10)

        s.prox_right = int(value[6])
        s.prox_left = int(value[7])
        s.prox_rear = int(value[8])

        yaw = _signed((value[13] << 8) | value[12], 12)
        s.yaw_delta = yaw - s.yaw
        s.yaw = yaw

        s.left_wheel = (value[15] << 8) | value[14]
        s.right_wheel = (value[17] << 8) | value[16]
        s.head_pitch = int(value[18])
        s.head_yaw = int(value[19])

        s.wheel_distance = _signed(
            ((value[9] & 0x0F) << 12) | (value[11] << 8) | value[10],
            16,
        )

    async def stop(self):
        self._motion_until = 0.0
        self._continuous_linear = 0.0
        self._continuous_angular = 0.0
        await self._command(CMD_DRIVE, bytes([0, 0, 0]))

    @staticmethod
    def _encode_drive_value(value: float) -> int:
        raw = max(-2048, min(2047, int(value)))
        if raw < 0:
            raw = 0x800 + raw
        return raw & 0x0FFF

    async def set_velocity(self, linear: float, angular: float):
        """
        Set continuous normalized velocity.

        linear:  -1.0 reverse .. +1.0 forward
        angular: -1.0 right   .. +1.0 left

        Dash keeps the command active until a later drive command or stop.
        """
        linear = max(-1.0, min(1.0, float(linear)))
        angular = max(-1.0, min(1.0, float(angular)))

        linear_raw = self._encode_drive_value(linear * self.max_linear_raw)
        angular_raw = self._encode_drive_value(angular * self.max_angular_raw)

        # The third byte packs the high 4 bits of linear in bits 0..3
        # and the high 4 bits of angular in bits 3..6, matching the
        # community drive/spin encodings.
        packed_high = (
            ((linear_raw & 0x0F00) >> 8)
            | ((angular_raw & 0x0F00) >> 5)
        ) & 0xFF

        await self._command(
            CMD_DRIVE,
            bytes([
                linear_raw & 0xFF,
                angular_raw & 0xFF,
                packed_high,
            ]),
        )
        self._motion_until = 0.0
        self._continuous_linear = linear
        self._continuous_angular = angular

    async def head_yaw(self, degrees: int):
        degrees = max(-53, min(53, int(degrees)))
        await self._command(CMD_HEAD_YAW, bytes([degrees & 0xFF]))

    async def head_pitch(self, degrees: int):
        degrees = max(-5, min(10, int(degrees)))
        await self._command(CMD_HEAD_PITCH, bytes([degrees & 0xFF]))

    async def say(self, sound: str):
        payload = SOUNDS.get(sound)
        if payload:
            await self._command(CMD_SAY, payload)

    @staticmethod
    def _bounded_move_payload(
        distance_mm: int = 0,
        degrees: float = 0.0,
        duration_ms: int = 200,
    ) -> bytes:
        if distance_mm and degrees:
            raise ValueError("bounded command cannot move and turn simultaneously")

        distance_mm = int(distance_mm)
        duration_ms = max(40, min(2000, int(duration_ms)))

        distance_low = distance_mm & 0xFF
        distance_high = (distance_mm & 0x3F00) >> 8

        centiradians = int(math.radians(float(degrees)) * 100.0)
        turn_low = centiradians & 0xFF
        turn_high = (centiradians & 0x0300) >> 2

        sixth = distance_high | turn_high
        seventh = 0xC0 if centiradians < 0 else 0x00
        eighth = 0x81 if distance_mm < 0 else 0x80

        return bytes([
            distance_low,
            0x00,
            turn_low,
            (duration_ms >> 8) & 0xFF,
            duration_ms & 0xFF,
            sixth,
            seventh,
            eighth,
        ])

    async def move_bounded(self, distance_mm: int, duration_ms: int = 200):
        await self.stop()
        payload = self._bounded_move_payload(
            distance_mm=distance_mm,
            duration_ms=duration_ms,
        )
        await self._command(CMD_MOVE, payload)
        self._motion_until = time.monotonic() + duration_ms / 1000.0

    async def turn_bounded(self, degrees: float, duration_ms: int = 200):
        await self.stop()
        payload = self._bounded_move_payload(
            degrees=degrees,
            duration_ms=duration_ms,
        )
        await self._command(CMD_MOVE, payload)
        self._motion_until = time.monotonic() + duration_ms / 1000.0
