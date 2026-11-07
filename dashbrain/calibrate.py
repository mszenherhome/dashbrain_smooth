from __future__ import annotations

import argparse
import asyncio

from .config import load_config
from .dash_ble import DashBLE

async def run(config_path):
    cfg = load_config(config_path)
    drive_cfg = cfg.get("continuous_drive", {})
    robot = DashBLE(
        cfg.get("dash_address"),
        max_linear_raw=int(drive_cfg.get("max_linear_raw", 180)),
        max_angular_raw=int(drive_cfg.get("max_angular_raw", 160)),
    )
    await robot.connect()

    print(
        "Move your hand/object to known distances in front of left/right/rear sensors.\n"
        "The community implementation treats HIGHER proximity values as CLOSER.\n"
        "Ctrl+C when finished."
    )

    try:
        while True:
            s = robot.state
            print(
                f"L={s.prox_left:3d}  R={s.prox_right:3d}  rear={s.prox_rear:3d}",
                end="\r",
                flush=True,
            )
            await asyncio.sleep(0.1)
    finally:
        print()
        await robot.disconnect()

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default=None)
    args = p.parse_args()
    asyncio.run(run(args.config))

if __name__ == "__main__":
    main()
