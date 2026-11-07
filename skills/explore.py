NAME = "explore"
PRIORITY = 40
INTERVAL_MS = 100

def step():
    mode = fact("mode", "explore")

    if mode == "pause":
        set_fact("desired_turn", 0.0)
        return velocity(linear=0.0, angular=0.0, priority=60)

    left = sensor("prox_left", 0)
    right = sensor("prox_right", 0)

    stop_threshold = fact("prox_stop_threshold", 100)
    soft_threshold = max(
        fact("prox_slow_threshold", int(stop_threshold * 0.60)),
        int(stop_threshold * 0.45),
    )
    turn_threshold = int(stop_threshold * 0.82)
    clear_threshold = int(stop_threshold * 0.62)

    blocked = local_get("blocked", False)

    # Only stop-and-pivot when the obstacle is genuinely near.
    if left >= turn_threshold or right >= turn_threshold:
        local_set("blocked", True)

        if left > right:
            angular = -0.48
        elif right > left:
            angular = 0.48
        else:
            last_turn = local_get("last_escape_turn", 1)
            angular = -0.48 * last_turn
            local_set("last_escape_turn", -last_turn)

        set_fact("desired_turn", angular)
        return velocity(linear=0.0, angular=angular, priority=55)

    # Hysteresis prevents stop/go chatter at the edge of an obstacle.
    if blocked:
        if left > clear_threshold or right > clear_threshold:
            if left > right:
                angular = -0.34
            else:
                angular = 0.34

            set_fact("desired_turn", angular)
            return velocity(linear=0.0, angular=angular, priority=52)

        local_set("blocked", False)

    # Normal exploration is forward-biased.
    # Larger left proximity => obstacle left => steer right (negative angular).
    difference = right - left
    angular = difference / 150.0
    angular = max(-0.24, min(0.24, angular))

    nearest = max(left, right)

    # Very small, slow wandering bias in genuinely open space.
    if nearest < soft_threshold:
        phase = int(now() / 8) % 4
        if phase == 0:
            angular = angular - 0.03
        elif phase == 2:
            angular = angular + 0.03

    # Move continuously while there is usable space.
    if nearest < soft_threshold:
        linear = 0.60
    else:
        span = max(1, turn_threshold - soft_threshold)
        closeness = (nearest - soft_threshold) / span
        closeness = max(0.0, min(1.0, closeness))
        linear = 0.60 - 0.30 * closeness

    if mode == "cautious":
        linear = min(linear, 0.38)

    if mode == "inspect":
        linear = min(linear, 0.30)

    set_fact("desired_turn", angular)

    return velocity(
        linear=linear,
        angular=angular,
        priority=40,
    )
