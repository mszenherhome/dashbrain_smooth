NAME = "button_attention"
PRIORITY = 75
INTERVAL_MS = 120

def step():
    pressed = sensor("button_main", False)
    was_pressed = local_get("was_pressed", False)
    local_set("was_pressed", pressed)

    if pressed and not was_pressed:
        return [
            velocity(0.0, 0.0, priority=95),
            head(0, priority=60),
            sound("hi", priority=40),
            signal(
                "ask_llm",
                {"reason": "The human pressed Dash's main button."},
                priority=70,
            ),
        ]

    return None
