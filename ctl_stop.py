#!/usr/bin/python3
"""M Focus: end the running session now (the app asks for the admin password first)."""
import json
import os
import subprocess
import sys
import tempfile
import time

DIR = os.environ.get("MFOCUS_DIR", "/var/lib/mfocus")
STATE = os.path.join(DIR, "state.json")


def truncate(state, now):
    keep = []
    for p in state["phases"]:
        if p["start"] >= now:
            continue
        p["end"] = min(p["end"], now)
        keep.append(p)
    state["phases"], state["end"] = keep, now
    return state


def main():
    if os.geteuid() != 0 and not os.environ.get("MFOCUS_TEST"):
        sys.exit("must run as root")
    try:
        with open(STATE) as f:
            state = json.load(f)
    except (OSError, ValueError):
        sys.exit("no session running")
    state = truncate(state, int(time.time()))
    fd, tmp = tempfile.mkstemp(dir=DIR, prefix=".mf-")
    with os.fdopen(fd, "w") as f:
        json.dump(state, f)
    os.chmod(tmp, 0o644)
    os.replace(tmp, STATE)
    if not os.environ.get("MFOCUS_TEST"):
        subprocess.run(["systemctl", "start", "mfocus.service"], check=False)
    print("stopping")


if __name__ == "__main__":
    main()
