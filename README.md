# DashBrain

A Raspberry Pi 4 autonomy stack for Wonder Workshop Dash.

This version is tuned for **smooth, forward-biased exploration**:

- clear space -> keep moving forward continuously
- mild left/right proximity imbalance -> gently curve away
- genuinely near obstacle -> stop forward translation and pivot
- once clear -> immediately resume forward motion
- head generally faces the direction of travel with small, slow variation
- full stop-and-scan behavior is no longer the normal exploration mode

The Pi runs the entire stack locally: Bluetooth, fast reactive agents, immutable
safety checks, and a local `llama.cpp` strategic agent.

## Architecture

```text
Dash BLE sensors
      |
      v
  World model
      |
      +------------------------+
      |                        |
      v                        v
Fast Python skills        Strategic LLM
  5-10 Hz                 slow / event-driven
      |                        |
      +-----------+------------+
                  |
             action intents
                  |
             Safety kernel
                  |
        continuous velocity/head
                  |
                 Dash
```

The LLM may create, modify, enable, disable, and roll back fast Python skills,
but generated skills cannot access the safety kernel directly.

## Safety boundary

LLM-generated skills are real Python, but deliberately restricted:

- no imports
- no filesystem/network/subprocess access
- no reflection/eval/exec
- no classes
- no attribute access
- no loops/comprehensions
- only `step()` and optional `handle(payload)`
- robot actions only through the supplied skill API

This is a reliability boundary, not a formal hostile-code sandbox. For adversarial
code isolation, use an OS-level process/container sandbox.

## Install on Raspberry Pi OS 64-bit

```bash
sudo apt update
sudo apt install -y \
    bluetooth bluez python3-venv python3-dev \
    git cmake build-essential

cd ~
unzip dashbrain.zip
cd dashbrain

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Check Bluetooth:

```bash
bluetoothctl
power on
scan on
```

Make sure Dash is powered on and not already connected to another controller.

## llama.cpp

Build if needed:

```bash
cd ~
git clone https://github.com/ggml-org/llama.cpp.git
cd llama.cpp
cmake -B build
cmake --build build -j4 --target llama-server llama-cli
```

Then:

```bash
cd ~/dashbrain
./scripts/start_llama.sh ~/models/Qwen3-0.6B-Q4_0.gguf
```

The supplied launcher uses:

```text
context: 4096
inference threads: 2
batch threads: 2
host: 127.0.0.1
port: 8080
```

DashBrain's LLM client uses a 600-second read timeout and a 250-token normal
strategy response budget. Code-authoring calls get a larger response budget.

Health check:

```bash
curl http://127.0.0.1:8080/health
```

## Simulator first

Without the LLM:

```bash
python -m dashbrain.main --simulate --no-llm
```

With the LLM server running:

```bash
python -m dashbrain.main --simulate
```

The simulator does not model a room; it exercises the orchestration, skills,
LLM, state, and continuous velocity path.

## Calibrate proximity before real translation

The shipped configuration contains:

```json
"proximity_calibrated": false
```

so the safety kernel blocks forward/reverse translation until you explicitly
calibrate.

Run:

```bash
python -m dashbrain.calibrate
```

Measure left/right/rear values with open space and with an object at several
known distances. This project assumes larger raw values mean a nearer object.

Then edit `config.json`, choose conservative values, and set:

```json
"proximity_stop_threshold": 100,
"proximity_slow_threshold": 60,
"proximity_calibrated": true
```

Use your own measured values rather than blindly accepting those examples.

## Smooth exploration behavior

`skills/explore.py` is now a continuous reactive controller.

In open space it normally asks for roughly:

```text
linear = 0.60
angular ~= 0
```

If the left proximity sensor sees more obstruction than the right, Dash curves
right while continuing to move. The opposite happens for a right-side obstacle.

Only when proximity reaches about 82% of the hard-stop threshold does the normal
explorer drop linear velocity to zero and pivot in place. Hysteresis keeps it
from chattering between drive/turn states.

All continuous commands are still filtered by the immutable safety kernel.

Raw motor scaling is separate in `config.json`:

```json
"continuous_drive": {
  "max_linear_raw": 180,
  "max_angular_raw": 160
}
```

Tune these conservatively on the real robot.

## Head behavior

`skills/head_scan.py` is retained by name for compatibility, but it no longer
does continuous left/center/right scanning.

It looks mostly in the direction of travel, with a small slow variation. Tiny
corrections are suppressed to prevent head jitter.

## Obstacle agent

`obstacle_avoid.py` is retained but **disabled by default** because the smooth
explorer already handles normal obstacle avoidance and the immutable safety
kernel provides the hard stop.

Check:

```bash
python -m dashbrain.skillctl list
```

You should see `obstacle_avoid` as OFF.

## Human questions over SSH

In a second SSH session:

```bash
cd ~/dashbrain
source .venv/bin/activate
python -m dashbrain.interact
```

If the strategic agent asks something:

```text
DASH: I keep encountering something in the same direction. Is there a wall there?
YOU:
```

The answer becomes part of the world model.

## Personality

Edit:

```text
personality.txt
```

The strategic agent reloads it each cycle; no restart is needed.

The default personality favors safe, smooth, curious exploration.

## Fast skill API

A skill may use:

```text
sensor(key, default=None)
fact(key, default=None)
set_fact(key, value)

local_get(key, default=None)
local_set(key, value)

now()

velocity(linear=0.0, angular=0.0, priority=50)
motion(kind, amount=0, duration_ms=180, priority=50)

head(yaw=0, pitch=None, priority=20)
sound(name, priority=10)
signal(name, data=None, priority=10)
call_skill(name, payload=None)
```

`velocity()` is the preferred primitive for smooth recurring movement.

`motion()` is still available for short discrete recovery maneuvers such as a
brief backup when stuck.

## LLM-generated skills

The strategist may request:

```text
create_skill
modify_skill
enable_skill
disable_skill
rollback_skill
```

Create/modify workflow:

1. same local model enters the skill-author role
2. personality/world/current source are supplied
3. candidate source is AST validated
4. it is smoke-tested with synthetic sensor state
5. previous source is archived
6. new source is atomically installed
7. activation is controlled by the manifest

New LLM-created skills default to OFF:

```json
"auto_activate_new": false
```

This is intentional while you evaluate the generated code.

## Manage skills

```bash
python -m dashbrain.skillctl list
python -m dashbrain.skillctl show explore
python -m dashbrain.skillctl disable explore
python -m dashbrain.skillctl enable explore
python -m dashbrain.skillctl rollback explore
```

Archived prior versions are stored under:

```text
runtime/archive/
```

## Run the real robot

After calibration:

```bash
cd ~/dashbrain
source .venv/bin/activate
python -m dashbrain.main
```

or:

```bash
./scripts/run_robot.sh
```

## Optional user systemd services

Copy the supplied unit files:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/llama.service ~/.config/systemd/user/
cp systemd/dashbrain.service ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable --now llama.service
systemctl --user enable --now dashbrain.service
```

If your model filename differs, edit the copied `llama.service`.

## Recommended tuning sequence

1. Run simulator with `--no-llm`.
2. Calibrate proximity sensors.
3. Run the real robot at conservative motor scales.
4. Tune `max_linear_raw` / `max_angular_raw`.
5. Tune proximity stop/slow thresholds.
6. Only then enable full LLM strategy.
7. Keep auto-activation of generated skills OFF until you trust the workflow.
