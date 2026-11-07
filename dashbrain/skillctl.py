from __future__ import annotations

import argparse

from .config import ROOT, load_config
from .skill_manager import SkillManager
from .world import WorldModel

def main():
    parser = argparse.ArgumentParser(
        description="Inspect/manage DashBrain fast skills"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list")

    for command in ("enable", "disable", "show", "rollback"):
        sp = sub.add_parser(command)
        sp.add_argument("name")

    args = parser.parse_args()

    cfg = load_config()
    world = WorldModel()
    manager = SkillManager(ROOT, world, cfg)

    if args.command == "list":
        for s in manager.list_skills():
            mark = "ON " if s["enabled"] else "OFF"
            print(
                f"{mark:3}  {s['name']:<24} "
                f"priority={s['priority']:<3} interval={s['interval_ms']}ms"
            )

    elif args.command == "enable":
        manager.enable(args.name)
        print(f"enabled {args.name}")

    elif args.command == "disable":
        manager.disable(args.name)
        print(f"disabled {args.name}")

    elif args.command == "show":
        print(manager.read_source(args.name))

    elif args.command == "rollback":
        archived = manager.rollback(args.name)
        print(f"rolled {args.name} back using {archived}")

if __name__ == "__main__":
    main()
