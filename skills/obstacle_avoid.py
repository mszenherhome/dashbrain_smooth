NAME = "obstacle_avoid"
PRIORITY = 90
INTERVAL_MS = 80

def step():
    # Disabled by default. This is an optional emergency-style fast agent.
    threshold = fact("prox_stop_threshold", 100)
    left = sensor("prox_left", 0)
    right = sensor("prox_right", 0)

    if sensor("picked_up", False) or sensor("on_side", False):
        return velocity(0.0, 0.0, priority=100)

    if left >= threshold or right >= threshold:
        if left > right:
            turn = -0.55
        else:
            turn = 0.55
        set_fact("desired_turn", turn)
        return velocity(0.0, turn, priority=95)

    return None
