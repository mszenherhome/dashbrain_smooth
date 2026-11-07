from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

class HumanChannel:
    """
    File-backed question/answer channel.

    Run `python -m dashbrain.interact` in another SSH session to answer.
    """

    def __init__(self, runtime_dir: Path, timeout_s: float = 90):
        self.runtime_dir = runtime_dir
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.question_path = runtime_dir / "question.json"
        self.answer_path = runtime_dir / "answer.json"
        self.timeout_s = timeout_s

    async def ask(self, question: str) -> str | None:
        qid = f"{time.time_ns()}"
        self.answer_path.unlink(missing_ok=True)
        self.question_path.write_text(json.dumps({
            "id": qid,
            "question": question,
            "created_at": time.time(),
        }, indent=2))

        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            if self.answer_path.exists():
                try:
                    answer = json.loads(self.answer_path.read_text())
                    if answer.get("id") == qid:
                        self.question_path.unlink(missing_ok=True)
                        self.answer_path.unlink(missing_ok=True)
                        return str(answer.get("answer", "")).strip()
                except Exception:
                    pass
            await asyncio.sleep(0.5)

        self.question_path.unlink(missing_ok=True)
        return None
