NAME = "head_scan"
PRIORITY = 20
INTERVAL_MS = 500

def step():
    mode = fact("mode", "explore")

    if mode == "pause":
        return head(0, priority=20)

    turn = fact("desired_turn", 0.0)

    # Dash head yaw uses negative values for left and positive for right in
    # this project, while positive angular velocity means turning left.
    target = int(-turn * 36)

    # Small, slow variation keeps the head from looking mechanically fixed
    # without returning to constant left/right scanning.
    phase = int(now() / 7) % 4
    if phase == 0:
        variation = -4
    elif phase == 2:
        variation = 4
    else:
        variation = 0

    target = target + variation
    target = max(-18, min(18, target))

    last_target = local_get("last_target", 999)

    # Suppress tiny repetitive corrections.
    if abs(target - last_target) < 4:
        return None

    local_set("last_target", target)
    return head(target, priority=20)
