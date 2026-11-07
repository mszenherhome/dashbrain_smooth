from __future__ import annotations

import ast
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SAFE_BUILTINS = {
    "abs": abs,
    "min": min,
    "max": max,
    "int": int,
    "float": float,
    "bool": bool,
    "str": str,
    "len": len,
    "round": round,
}

API_CALLS = {
    "sensor",
    "fact",
    "set_fact",
    "local_get",
    "local_set",
    "now",
    "motion",
    "velocity",
    "head",
    "sound",
    "signal",
    "call_skill",
    *SAFE_BUILTINS.keys(),
}

ALLOWED_NODES = (
    ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return,
    ast.Assign, ast.Expr, ast.Name, ast.Load, ast.Store, ast.Constant,
    ast.Call, ast.keyword, ast.If, ast.Compare, ast.BoolOp, ast.And, ast.Or,
    ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
    ast.Pow, ast.UnaryOp, ast.USub, ast.UAdd, ast.Not,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
    ast.Dict, ast.List, ast.Tuple, ast.Subscript, ast.Slice, ast.IfExp,
    ast.Pass,
)

class SkillValidationError(ValueError):
    pass

def validate_skill_source(source: str, max_chars: int = 12000, max_nodes: int = 500):
    if len(source) > max_chars:
        raise SkillValidationError(f"skill is too large ({len(source)} chars)")

    tree = ast.parse(source)
    nodes = list(ast.walk(tree))
    if len(nodes) > max_nodes:
        raise SkillValidationError(f"skill AST is too large ({len(nodes)} nodes)")

    function_names = set()

    for node in nodes:
        if not isinstance(node, ALLOWED_NODES):
            raise SkillValidationError(
                f"disallowed Python construct: {node.__class__.__name__}"
            )

        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise SkillValidationError(f"private/dunder name not allowed: {node.id}")

        if isinstance(node, ast.FunctionDef):
            if node.name not in {"step", "handle"}:
                raise SkillValidationError(
                    "skills may define only step() and optional handle(payload)"
                )
            function_names.add(node.name)

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise SkillValidationError("only direct calls to the skill API are allowed")
            if node.func.id not in API_CALLS:
                raise SkillValidationError(f"call not allowed: {node.func.id}")

    if "step" not in function_names:
        raise SkillValidationError("skill must define step()")

    return tree

@dataclass
class LoadedSkill:
    name: str
    path: Path
    priority: int
    interval_ms: int
    namespace: dict[str, Any]
    enabled: bool = True
    last_run: float = 0.0
    local_state: dict[str, Any] = field(default_factory=dict)
    consecutive_errors: int = 0

class SkillEngine:
    def __init__(self, world, config: dict[str, Any]):
        self.world = world
        self.cfg = config
        self.skills: dict[str, LoadedSkill] = {}
        self.enabled_manifest: dict[str, bool] = {}

    def _api_for(self, skill: LoadedSkill):
        def sensor(key, default=None):
            return self.world.sensor(str(key), default)

        def fact(key, default=None):
            return self.world.fact(str(key), default)

        def set_fact(key, value):
            self.world.set_fact(str(key), value)
            return value

        def local_get(key, default=None):
            return skill.local_state.get(str(key), default)

        def local_set(key, value):
            skill.local_state[str(key)] = value
            return value

        def now():
            return time.monotonic()

        def motion(kind, amount=0, duration_ms=180, priority=50):
            return {
                "type": "motion",
                "kind": str(kind),
                "amount": int(amount),
                "duration_ms": int(duration_ms),
                "priority": int(priority),
                "source": skill.name,
            }

        def velocity(linear=0.0, angular=0.0, priority=50):
            return {
                "type": "velocity",
                "linear": max(-1.0, min(1.0, float(linear))),
                "angular": max(-1.0, min(1.0, float(angular))),
                "priority": int(priority),
                "source": skill.name,
            }

        def head(yaw=0, pitch=None, priority=20):
            out = {
                "type": "head",
                "yaw": int(yaw),
                "priority": int(priority),
                "source": skill.name,
            }
            if pitch is not None:
                out["pitch"] = int(pitch)
            return out

        def sound(name, priority=10):
            return {
                "type": "sound",
                "name": str(name),
                "priority": int(priority),
                "source": skill.name,
            }

        def signal(name, data=None, priority=10):
            return {
                "type": "signal",
                "name": str(name),
                "data": data,
                "priority": int(priority),
                "source": skill.name,
            }

        def call_skill(name, payload=None):
            return self.call_skill(str(name), payload)

        return {
            "__builtins__": SAFE_BUILTINS,
            **SAFE_BUILTINS,
            "sensor": sensor,
            "fact": fact,
            "set_fact": set_fact,
            "local_get": local_get,
            "local_set": local_set,
            "now": now,
            "motion": motion,
            "velocity": velocity,
            "head": head,
            "sound": sound,
            "signal": signal,
            "call_skill": call_skill,
        }

    def load_source(self, path: Path, enabled: bool = True) -> LoadedSkill:
        source = path.read_text()
        validate_skill_source(
            source,
            max_chars=int(self.cfg["skills"]["max_skill_source_chars"]),
            max_nodes=int(self.cfg["skills"]["max_ast_nodes"]),
        )

        placeholder = LoadedSkill(
            name=path.stem,
            path=path,
            priority=50,
            interval_ms=100,
            namespace={},
            enabled=enabled,
        )
        namespace = self._api_for(placeholder)
        exec(compile(source, str(path), "exec"), namespace, namespace)

        name = str(namespace.get("NAME", path.stem))
        if name != path.stem:
            raise SkillValidationError(
                f"NAME must match filename stem ({path.stem!r}), got {name!r}"
            )

        placeholder.name = name
        placeholder.priority = int(namespace.get("PRIORITY", 50))
        placeholder.interval_ms = max(20, int(namespace.get("INTERVAL_MS", 100)))
        placeholder.namespace = namespace
        return placeholder

    def load_directory(self, directory: Path, enabled_manifest: dict[str, bool]):
        self.skills.clear()
        self.enabled_manifest = enabled_manifest
        for path in sorted(directory.glob("*.py")):
            enabled = enabled_manifest.get(path.stem, True)
            skill = self.load_source(path, enabled=enabled)
            self.skills[skill.name] = skill

    def call_skill(self, name: str, payload=None):
        skill = self.skills.get(name)
        if not skill or not skill.enabled:
            return None
        handler = skill.namespace.get("handle")
        if not handler:
            return None
        return handler(payload)

    @staticmethod
    def _flatten(value):
        if value is None:
            return []
        if isinstance(value, dict):
            return [value]
        if isinstance(value, (list, tuple)):
            return [item for item in value if isinstance(item, dict)]
        return []

    def step(self) -> list[dict]:
        now = time.monotonic()
        intents: list[dict] = []

        for skill in sorted(
            self.skills.values(),
            key=lambda s: s.priority,
            reverse=True,
        ):
            if not skill.enabled:
                continue
            if (now - skill.last_run) * 1000 < skill.interval_ms:
                continue

            skill.last_run = now
            try:
                value = skill.namespace["step"]()
                for intent in self._flatten(value):
                    intent.setdefault("source", skill.name)
                    intent.setdefault("priority", skill.priority)
                    intents.append(intent)
                skill.consecutive_errors = 0
            except Exception as exc:
                skill.consecutive_errors += 1
                self.world.add_event(
                    "skill_error",
                    {"skill": skill.name, "error": repr(exc)},
                    source="skill_engine",
                )
                if skill.consecutive_errors >= int(
                    self.cfg["skills"]["runtime_error_limit"]
                ):
                    skill.enabled = False
                    self.enabled_manifest[skill.name] = False
                    self.world.add_event(
                        "skill_auto_disabled",
                        {"skill": skill.name, "reason": "repeated runtime errors"},
                        source="skill_engine",
                    )

        return intents
