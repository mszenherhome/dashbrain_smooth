from __future__ import annotations

import argparse
import asyncio
import time

from .config import ROOT, load_config
from .dash_ble import DashBLE
from .human import HumanChannel
from .llm import LlamaClient
from .safety import SafetyKernel
from .simulator import SimulatedDash
from .skill_manager import SkillManager
from .strategist import Strategist
from .world import WorldModel

def choose(intents: list[dict], kind: str):
    candidates = [x for x in intents if x.get("type") == kind]
    if not candidates:
        return None
    return max(candidates, key=lambda x: int(x.get("priority", 0)))

def choose_actuation(intents: list[dict]):
    candidates = [
        x for x in intents
        if x.get("type") in {"velocity", "motion"}
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda x: int(x.get("priority", 0)))

async def execute_motion(robot, intent: dict, world: WorldModel):
    kind = intent.get("kind", "stop")
    amount = int(intent.get("amount", 0))
    duration_ms = int(intent.get("duration_ms", 180))

    if kind == "stop":
        await robot.stop()
    elif kind == "forward":
        await robot.move_bounded(abs(amount), duration_ms)
    elif kind == "backward":
        await robot.move_bounded(-abs(amount), duration_ms)
    elif kind == "turn_left":
        await robot.turn_bounded(-abs(amount), duration_ms)
    elif kind == "turn_right":
        await robot.turn_bounded(abs(amount), duration_ms)
    else:
        await robot.stop()
        kind = "stop"

    world.set_fact("last_motor_kind", kind)
    world.set_fact("commanded_linear", 0.0)
    world.set_fact("commanded_angular", 0.0)
    world.record_action({
        "type": "motion",
        "kind": kind,
        "amount": amount,
        "duration_ms": duration_ms,
        "source": intent.get("source"),
    })

async def run(args):
    cfg = load_config(args.config)
    world = WorldModel()

    world.set_fact(
        "prox_stop_threshold",
        int(cfg["proximity_stop_threshold"]),
    )
    world.set_fact(
        "prox_slow_threshold",
        int(cfg["proximity_slow_threshold"]),
    )

    if args.simulate:
        robot = SimulatedDash()
    else:
        drive_cfg = cfg.get("continuous_drive", {})
        robot = DashBLE(
            cfg.get("dash_address"),
            max_linear_raw=int(drive_cfg.get("max_linear_raw", 180)),
            max_angular_raw=int(drive_cfg.get("max_angular_raw", 160)),
        )

    await robot.connect()
    print("[robot] connected")

    if not cfg.get("proximity_calibrated", False):
        print(
            "[SAFETY] proximity_calibrated=false. Translation will be "
            "blocked until you calibrate the sensors and update config.json."
        )

    safety = SafetyKernel(cfg)
    skill_manager = SkillManager(ROOT, world, cfg)
    llm = LlamaClient(cfg)
    human = HumanChannel(
        ROOT / "runtime",
        timeout_s=float(cfg["human"]["question_timeout_s"]),
    )
    strategist = Strategist(
        ROOT,
        world,
        skill_manager,
        llm,
        human,
        cfg,
        personality_path=ROOT / "personality.txt",
    )

    stop_event = asyncio.Event()
    strategy_wakeup = asyncio.Event()

    async def sensor_loop():
        period = 0.05
        while not stop_event.is_set():
            if args.simulate:
                robot.tick()
            world.update_sensors(robot.state.snapshot())
            await asyncio.sleep(period)

    async def safety_loop():
        period = 1.0 / float(cfg["safety_hz"])
        while not stop_event.is_set():
            sensors = robot.state.snapshot()
            hazard, reason = safety.immediate_hazard(sensors)
            if hazard and robot.motion_active:
                try:
                    await robot.stop()
                    world.set_fact("last_motor_kind", "stop")
                    world.set_fact("commanded_linear", 0.0)
                    world.set_fact("commanded_angular", 0.0)
                    world.add_event(
                        "safety_stop",
                        {"reason": reason},
                        source="safety_kernel",
                    )
                except Exception as exc:
                    print("[safety] stop failed:", exc)
            await asyncio.sleep(period)

    async def control_loop():
        period = 1.0 / float(cfg["control_hz"])
        last_head = None
        last_sound_at = 0.0
        last_velocity = None
        last_velocity_sent = 0.0

        while not stop_event.is_set():
            intents = skill_manager.engine.step()

            for intent in intents:
                if intent.get("type") == "signal":
                    signal_name = intent.get("name", "skill_signal")
                    world.add_event(
                        signal_name,
                        intent.get("data"),
                        source=intent.get("source", "skill"),
                    )
                    if signal_name == "ask_llm":
                        strategy_wakeup.set()

            head_intent = choose(intents, "head")
            if head_intent:
                target = (
                    int(head_intent.get("yaw", 0)),
                    head_intent.get("pitch"),
                )
                if target != last_head:
                    await robot.head_yaw(target[0])
                    if target[1] is not None:
                        await robot.head_pitch(int(target[1]))
                    last_head = target

            sound_intent = choose(intents, "sound")
            if sound_intent and time.monotonic() - last_sound_at > 2.0:
                await robot.say(str(sound_intent.get("name", "confused")))
                last_sound_at = time.monotonic()

            actuation = choose_actuation(intents)

            # Let a bounded recovery maneuver finish before returning to the
            # continuous controller, unless an explicit stop has higher priority.
            if robot.bounded_motion_active:
                if (
                    actuation
                    and actuation.get("type") == "motion"
                    and actuation.get("kind") == "stop"
                ):
                    filtered, _ = safety.filter_motion(
                        actuation,
                        robot.state.snapshot(),
                    )
                    await execute_motion(robot, filtered, world)
                await asyncio.sleep(period)
                continue

            if actuation is None:
                # No skill currently requests motion: fail to a stop rather than
                # letting a stale continuous command persist indefinitely.
                if last_velocity != (0.0, 0.0):
                    await robot.stop()
                    last_velocity = (0.0, 0.0)
                    last_velocity_sent = time.monotonic()
                    world.set_fact("last_motor_kind", "stop")
                    world.set_fact("commanded_linear", 0.0)
                    world.set_fact("commanded_angular", 0.0)

            elif actuation.get("type") == "velocity":
                filtered, reason = safety.filter_velocity(
                    actuation,
                    robot.state.snapshot(),
                )

                if reason:
                    world.add_event(
                        "safety_veto",
                        {"reason": reason, "requested": actuation},
                        source="safety_kernel",
                    )

                linear = float(filtered.get("linear", 0.0))
                angular = float(filtered.get("angular", 0.0))
                pair = (round(linear, 3), round(angular, 3))

                # Send on changes, plus a periodic refresh. Avoiding redundant
                # BLE writes makes the motion/control loop smoother.
                changed = (
                    last_velocity is None
                    or abs(pair[0] - last_velocity[0]) >= 0.02
                    or abs(pair[1] - last_velocity[1]) >= 0.02
                )
                refresh_due = time.monotonic() - last_velocity_sent >= 0.5

                if changed or refresh_due:
                    await robot.set_velocity(linear, angular)
                    last_velocity = pair
                    last_velocity_sent = time.monotonic()

                world.set_fact(
                    "last_motor_kind",
                    "velocity" if abs(linear) + abs(angular) > 0 else "stop",
                )
                world.set_fact("commanded_linear", linear)
                world.set_fact("commanded_angular", angular)

            else:
                filtered, reason = safety.filter_motion(
                    actuation,
                    robot.state.snapshot(),
                )
                if reason:
                    world.add_event(
                        "safety_veto",
                        {"reason": reason, "requested": actuation},
                        source="safety_kernel",
                    )
                await execute_motion(robot, filtered, world)
                last_velocity = None

            await asyncio.sleep(period)

    async def strategy_loop():
        await asyncio.sleep(4.0)
        while not stop_event.is_set():
            strategy_wakeup.clear()

            try:
                await strategist.run_once()
            except Exception as exc:
                world.add_event(
                    "strategist_error",
                    {"error": repr(exc)},
                    source="strategist",
                )
                print("[strategist]", repr(exc))

            try:
                await asyncio.wait_for(
                    strategy_wakeup.wait(),
                    timeout=float(cfg["strategy_interval_s"]),
                )
            except asyncio.TimeoutError:
                pass

    tasks = [
        asyncio.create_task(sensor_loop(), name="sensor"),
        asyncio.create_task(safety_loop(), name="safety"),
        asyncio.create_task(control_loop(), name="control"),
    ]

    if not args.no_llm:
        tasks.append(
            asyncio.create_task(strategy_loop(), name="strategy")
        )

    try:
        while True:
            await asyncio.sleep(5)
            summary = world.summary()
            print(
                "[status]",
                "mode=", summary["facts"].get("mode"),
                "prox=",
                summary["sensors"].get("prox_left"),
                summary["sensors"].get("prox_right"),
                summary["sensors"].get("prox_rear"),
                "v=", round(float(summary["facts"].get("commanded_linear", 0)), 2),
                "w=", round(float(summary["facts"].get("commanded_angular", 0)), 2),
                "skills=",
                [
                    s["name"]
                    for s in skill_manager.list_skills()
                    if s["enabled"]
                ],
            )
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        stop_event.set()
        for t in tasks:
            t.cancel()
        try:
            await robot.stop()
        except Exception:
            pass
        await robot.disconnect()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config.json"))
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--no-llm", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args))

if __name__ == "__main__":
    main()
