from __future__ import annotations

import time

from .config import load_personality

STRATEGY_SYSTEM = """
You are the strategic executive for a Wonder Workshop Dash robot.

The robot has an immutable deterministic safety kernel. Fast Python skills handle
recurring sensor-to-action behavior. Normal exploration should be smooth and
forward-biased: keep moving through clear space, use gentle steering corrections,
stop/pivot only near obstacles, and keep the head generally facing the direction
of travel with small variations.

You should make higher-level decisions: choose modes/goals, decide whether a
human question is worthwhile, enable/disable skills, and decide when a recurring
behavior should become a new or improved skill.

The current personality is supplied in the request and is an important input.

You may return these action objects:
  {"kind":"set_mode","value":"explore|cautious|pause|inspect"}
  {"kind":"set_directive","value":"short strategic directive"}
  {"kind":"ask_human","question":"concise question"}
  {"kind":"enable_skill","name":"skill_name"}
  {"kind":"disable_skill","name":"skill_name"}
  {"kind":"create_skill","name":"skill_name","purpose":"what recurring behavior it adds"}
  {"kind":"modify_skill","name":"skill_name","purpose":"specific improvement"}
  {"kind":"rollback_skill","name":"skill_name"}
  {"kind":"noop"}

Prefer fast skills for recurring behavior. Create/modify a skill only when there
is a clear recurring sensor-process-action pattern that should run faster than
LLM reasoning. Do not attempt to modify the immutable safety kernel. Do not
create a skill merely to perform one immediate movement.

Return JSON only:
{
  "summary": "brief explanation of the strategic choice",
  "actions": [ ... ]
}
"""

SKILL_AUTHOR_SYSTEM = """
You write small reactive Python skills for a Wonder Workshop Dash robot.

The output is installed and run repeatedly, so keep it narrow and deterministic.
It is REAL Python but intentionally restricted.

STRICT RULES:
- No imports.
- No classes.
- No attribute access (no x.y).
- No loops or comprehensions.
- No filesystem, network, subprocess, eval, exec, reflection, threading or async.
- Define NAME, PRIORITY, INTERVAL_MS and def step():.
- Optional: def handle(payload): for calls from another skill.
- NAME must exactly equal the requested skill name.
- Return None, one intent dictionary, or a list/tuple of intent dictionaries.
- Motor actions are later checked by the immutable safety kernel.
- Prefer velocity() for smooth recurring exploration/steering behavior.
- Use bounded motion() mainly for discrete recovery maneuvers.

Available functions:
  sensor(key, default=None)
  fact(key, default=None)
  set_fact(key, value)
  local_get(key, default=None)
  local_set(key, value)
  now()

  velocity(linear=0.0, angular=0.0, priority=50)
      continuous normalized command:
      linear:  -1.0 reverse .. +1.0 forward
      angular: -1.0 right   .. +1.0 left

  motion(kind, amount=0, duration_ms=180, priority=50)
      bounded discrete command:
      kind: "forward", "backward", "turn_left", "turn_right", "stop"
      amount: millimeters for forward/backward, degrees for turns

  head(yaw=0, pitch=None, priority=20)
  sound(name, priority=10)
      supported names include "hi", "ohno", "confused", "charge", "elephant"
  signal(name, data=None, priority=10)
      use signal("ask_llm", {...}) to escalate an interesting event
  call_skill(name, payload=None)

  abs, min, max, int, float, bool, str, len, round

Useful sensor keys:
prox_left, prox_right, prox_rear, yaw, yaw_delta, left_wheel, right_wheel,
wheel_distance, head_yaw, head_pitch, picked_up, hit, on_side, clap, mic_level,
sound_direction, acceleration.

Useful facts include:
mode, directive, last_human_answer, last_motor_kind, commanded_linear,
commanded_angular, desired_turn, prox_stop_threshold, prox_slow_threshold.

Return JSON only:
{
  "name": "requested_name",
  "reason": "what this skill does",
  "activate": true,
  "code": "complete Python source code"
}
"""

class Strategist:
    def __init__(
        self,
        root,
        world,
        skill_manager,
        llm,
        human,
        config,
        personality_path=None,
    ):
        self.root = root
        self.world = world
        self.skills = skill_manager
        self.llm = llm
        self.human = human
        self.cfg = config
        self.personality_path = personality_path
        self.last_code_change = 0.0

    async def _author_skill(self, name: str, purpose: str, existing: str | None):
        request = {
            "requested_name": name,
            "purpose": purpose,
            "personality": load_personality(self.personality_path),
            "existing_source": existing,
            "current_world": self.world.summary(),
        }
        return await self.llm.chat_json(
            SKILL_AUTHOR_SYSTEM,
            request,
            max_tokens=1000,
        )

    async def _apply_code_change(self, action: dict):
        if not self.cfg["skills"].get("allow_llm_code_changes", True):
            return

        cooldown = float(self.cfg["skills"]["min_seconds_between_code_changes"])
        if time.monotonic() - self.last_code_change < cooldown:
            self.world.add_event(
                "code_change_deferred",
                {"action": action, "reason": "code-change cooldown"},
                source="strategist",
            )
            return

        kind = action.get("kind")
        name = str(action.get("name", "")).strip()
        purpose = str(action.get("purpose", "")).strip()
        existing = None

        if kind == "modify_skill":
            existing = self.skills.read_source(name)

        authored = await self._author_skill(name, purpose, existing)
        code = str(authored["code"]).strip()

        if code.startswith("```"):
            lines = code.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            code = "\n".join(lines).strip()

        activate = bool(authored.get("activate", False))
        self.skills.install(name, code, activate=activate)
        self.last_code_change = time.monotonic()

        self.world.add_event(
            "skill_installed",
            {
                "name": name,
                "reason": authored.get("reason"),
                "active": activate,
            },
            source="strategist",
        )

    async def run_once(self):
        request = {
            "personality": load_personality(self.personality_path),
            "world": self.world.summary(),
            "skills": self.skills.list_skills(),
        }

        plan = await self.llm.chat_json(STRATEGY_SYSTEM, request)
        self.world.add_event(
            "strategy",
            {
                "summary": plan.get("summary"),
                "actions": plan.get("actions", []),
            },
            source="strategist",
        )

        code_changed = False

        for action in plan.get("actions", []):
            kind = action.get("kind")

            try:
                if kind == "set_mode":
                    value = str(action.get("value", "explore"))
                    if value in {"explore", "cautious", "pause", "inspect"}:
                        self.world.set_fact("mode", value)

                elif kind == "set_directive":
                    self.world.set_fact(
                        "directive",
                        str(action.get("value", ""))[:500],
                    )

                elif kind == "ask_human":
                    question = str(action.get("question", "")).strip()
                    if question:
                        answer = await self.human.ask(question)
                        if answer:
                            self.world.set_fact("last_human_answer", answer)
                            self.world.add_event(
                                "human_answer",
                                {"question": question, "answer": answer},
                                source="human",
                            )
                        else:
                            self.world.add_event(
                                "human_no_answer",
                                {"question": question},
                                source="human",
                            )

                elif kind == "enable_skill":
                    self.skills.enable(str(action["name"]))

                elif kind == "disable_skill":
                    self.skills.disable(str(action["name"]))

                elif kind == "rollback_skill":
                    archived = self.skills.rollback(str(action["name"]))
                    self.world.add_event(
                        "skill_rollback",
                        {"name": action["name"], "from": archived},
                        source="strategist",
                    )

                elif kind in {"create_skill", "modify_skill"} and not code_changed:
                    await self._apply_code_change(action)
                    code_changed = True

            except Exception as exc:
                self.world.add_event(
                    "strategy_action_error",
                    {"action": action, "error": repr(exc)},
                    source="strategist",
                )
