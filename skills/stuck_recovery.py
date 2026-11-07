NAME = "stuck_recovery"
PRIORITY = 80
INTERVAL_MS = 250

def step():
    left = sensor("left_wheel", 0)
    right = sensor("right_wheel", 0)

    prev_left = local_get("prev_left", left)
    prev_right = local_get("prev_right", right)
    changed_at = local_get("changed_at", now())

    if left != prev_left or right != prev_right:
        local_set("prev_left", left)
        local_set("prev_right", right)
        local_set("changed_at", now())
        return None

    commanded_linear = fact("commanded_linear", 0.0)

    if commanded_linear > 0.25 and now() - changed_at > 1.5:
        local_set("changed_at", now())
        return [
            motion("backward", amount=18, duration_ms=180, priority=82),
            signal(
                "stuck_detected",
                {"left_wheel": left, "right_wheel": right},
                priority=70,
            ),
        ]

    return None
