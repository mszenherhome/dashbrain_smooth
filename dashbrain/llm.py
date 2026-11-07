from __future__ import annotations

import json
import re

import httpx

class LlamaClient:
    def __init__(self, config: dict):
        llm = config["llm"]
        self.url = llm["base_url"].rstrip("/") + "/chat/completions"
        self.model = llm.get("model", "local")
        self.timeout_s = float(llm.get("timeout_s", 600))
        self.temperature = float(llm.get("temperature", 0.10))
        self.max_tokens = int(llm.get("max_tokens", 250))

    @staticmethod
    def _extract_json(text: str):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if not m:
                raise ValueError(f"LLM did not return JSON: {text[:300]!r}")
            return json.loads(m.group(0))

    async def chat_json(
        self,
        system: str,
        user: dict,
        max_tokens: int | None = None,
    ):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
            ],
            "temperature": self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "response_format": {"type": "json_object"},
        }

        timeout = httpx.Timeout(
            connect=10.0,
            read=self.timeout_s,
            write=30.0,
            pool=10.0,
        )

        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(self.url, json=payload)
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
            return self._extract_json(text)
