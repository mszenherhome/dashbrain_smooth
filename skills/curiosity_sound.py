NAME = "curiosity_sound"
PRIORITY = 55
INTERVAL_MS = 150

def step():
    last = local_get("last_escalation", 0)
    clap = sensor("clap", False)
    mic = sensor("mic_level", 0)

    if clap and now() - last > 8:
        local_set("last_escalation", now())
        return [
            sound("confused", priority=30),
            signal(
                "ask_llm",
                {
                    "reason": "A clap or bump-like audio event was detected.",
                    "mic_level": mic,
                    "sound_direction": sensor("sound_direction", 0),
                },
                priority=55,
            ),
        ]

    if mic > 180 and now() - last > 15:
        local_set("last_escalation", now())
        return signal(
            "ask_llm",
            {
                "reason": "An unusually loud sound was detected.",
                "mic_level": mic,
                "sound_direction": sensor("sound_direction", 0),
            },
            priority=50,
        )

    return None
