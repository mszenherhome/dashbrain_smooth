from __future__ import annotations

import argparse
import json
import time

from .config import ROOT

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--poll", type=float, default=0.5)
    args = parser.parse_args()

    runtime = ROOT / "runtime"
    qpath = runtime / "question.json"
    apath = runtime / "answer.json"
    last_id = None

    print("Waiting for Dash questions. Ctrl+C to exit.")
    while True:
        if qpath.exists():
            try:
                q = json.loads(qpath.read_text())
                if q.get("id") != last_id:
                    last_id = q.get("id")
                    print(f"\nDASH: {q.get('question')}")
                    answer = input("YOU: ").strip()
                    apath.write_text(json.dumps({
                        "id": last_id,
                        "answer": answer,
                        "answered_at": time.time(),
                    }, indent=2))
            except (json.JSONDecodeError, OSError):
                pass
        time.sleep(args.poll)

if __name__ == "__main__":
    main()
