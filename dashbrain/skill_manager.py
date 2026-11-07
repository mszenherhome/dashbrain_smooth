from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from .skill_runtime import (
    SAFE_BUILTINS,
    SkillEngine,
    SkillValidationError,
    validate_skill_source,
)

class SkillManager:
    def __init__(self, root: Path, world, config: dict):
        self.root = root
        self.skills_dir = root / "skills"
        self.runtime_dir = root / "runtime"
        self.archive_dir = self.runtime_dir / "archive"
        self.manifest_path = self.runtime_dir / "skills.json"
        self.world = world
        self.cfg = config
        self.engine = SkillEngine(world, config)
        self.enabled = self._load_manifest()
        self.reload()

    def _load_manifest(self):
        if self.manifest_path.exists():
            return json.loads(self.manifest_path.read_text())
        return {}

    def _save_manifest(self):
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(self.enabled, indent=2))

    def reload(self):
        self.engine.load_directory(self.skills_dir, self.enabled)
        for name, skill in self.engine.skills.items():
            self.enabled.setdefault(name, skill.enabled)
        self._save_manifest()

    def list_skills(self):
        return [
            {
                "name": s.name,
                "enabled": s.enabled,
                "priority": s.priority,
                "interval_ms": s.interval_ms,
                "path": str(s.path),
            }
            for s in self.engine.skills.values()
        ]

    def enable(self, name: str):
        if name not in self.engine.skills:
            raise KeyError(name)
        self.enabled[name] = True
        self._save_manifest()
        self.reload()

    def disable(self, name: str):
        if name not in self.engine.skills:
            raise KeyError(name)
        self.enabled[name] = False
        self._save_manifest()
        self.reload()

    def read_source(self, name: str) -> str:
        p = self.skills_dir / f"{name}.py"
        if not p.exists():
            raise KeyError(name)
        return p.read_text()

    def _smoke_test(self, name: str, source: str):
        validate_skill_source(
            source,
            max_chars=int(self.cfg["skills"]["max_skill_source_chars"]),
            max_nodes=int(self.cfg["skills"]["max_ast_nodes"]),
        )

        locals_state = {}
        facts_state = {}
        fake_sensors = {
            "prox_left": 0, "prox_right": 0, "prox_rear": 0,
            "yaw": 0, "yaw_delta": 0, "wheel_distance": 0,
            "left_wheel": 0, "right_wheel": 0,
            "picked_up": False, "hit": False, "on_side": False,
            "clap": False, "mic_level": 0, "sound_direction": 0,
        }

        def sensor(k, default=None):
            return fake_sensors.get(str(k), default)
        def fact(k, default=None):
            return facts_state.get(str(k), default)
        def set_fact(k, v):
            facts_state[str(k)] = v
            return v
        def local_get(k, default=None):
            return locals_state.get(str(k), default)
        def local_set(k, v):
            locals_state[str(k)] = v
            return v
        def motion(kind, amount=0, duration_ms=180, priority=50):
            return {
                "type": "motion", "kind": str(kind), "amount": int(amount),
                "duration_ms": int(duration_ms), "priority": int(priority),
            }
        def velocity(linear=0.0, angular=0.0, priority=50):
            return {
                "type": "velocity", "linear": float(linear),
                "angular": float(angular), "priority": int(priority),
            }
        def head(yaw=0, pitch=None, priority=20):
            return {"type": "head", "yaw": int(yaw), "priority": int(priority)}
        def sound(name, priority=10):
            return {"type": "sound", "name": str(name), "priority": int(priority)}
        def signal(name, data=None, priority=10):
            return {
                "type": "signal", "name": str(name), "data": data,
                "priority": int(priority),
            }
        def call_skill(_name, _payload=None):
            return None

        ns = {
            "__builtins__": SAFE_BUILTINS,
            **SAFE_BUILTINS,
            "sensor": sensor, "fact": fact, "set_fact": set_fact,
            "local_get": local_get, "local_set": local_set,
            "now": time.monotonic,
            "motion": motion, "velocity": velocity,
            "head": head, "sound": sound, "signal": signal,
            "call_skill": call_skill,
        }
        exec(compile(source, f"<candidate:{name}>", "exec"), ns, ns)
        if str(ns.get("NAME", name)) != name:
            raise SkillValidationError("candidate NAME must match requested skill name")
        ns["step"]()

    def install(self, name: str, source: str, activate: bool | None = None):
        if not name.replace("_", "").isalnum() or name.startswith("_"):
            raise SkillValidationError("skill name must be letters/numbers/underscores")
        self._smoke_test(name, source)

        path = self.skills_dir / f"{name}.py"
        self.archive_dir.mkdir(parents=True, exist_ok=True)

        if path.exists():
            stamp = time.strftime("%Y%m%d-%H%M%S")
            shutil.copy2(path, self.archive_dir / f"{name}.{stamp}.py")

        tmp = path.with_suffix(".py.tmp")
        tmp.write_text(source)
        tmp.replace(path)

        if activate is None:
            activate = bool(self.cfg["skills"]["auto_activate_new"])
        self.enabled[name] = bool(activate)
        self._save_manifest()
        self.reload()

    def rollback(self, name: str):
        candidates = sorted(self.archive_dir.glob(f"{name}.*.py"))
        if not candidates:
            raise RuntimeError(f"no archived version exists for {name}")
        previous = candidates[-1]
        source = previous.read_text()
        self._smoke_test(name, source)
        (self.skills_dir / f"{name}.py").write_text(source)
        self.reload()
        return str(previous)
