#!/usr/bin/python3
"""M Focus: start a locked session (run through pkexec by the app).

Usage: ctl_start.py '<json>'
  {"label": "Physics",
   "phases": [["focus", 25], ["break", 5], ["focus", 25]],
   "domains": ["youtube.com", ...], "apps": ["discord", ...]}
Everything is validated here, because this program runs as root.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time

DIR = os.environ.get("MFOCUS_DIR", "/var/lib/mfocus")
STATE = os.path.join(DIR, "state.json")
DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9-]{1,63}\.)+[a-z]{2,63}$")
APP_RE = re.compile(r"^[A-Za-z0-9._+-]{1,15}$")


def build_state(req, now):
    if not isinstance(req, dict):
        raise ValueError("bad request")
    raw = req.get("phases")
    if not isinstance(raw, list) or not 1 <= len(raw) <= 48:
        raise ValueError("bad phases")
    phases, t = [], now
    for item in raw:
        try:
            kind, mins = item[0], item[1]
        except (TypeError, IndexError, KeyError):
            raise ValueError("bad phase")
        if kind not in ("focus", "break") or not isinstance(mins, int) or isinstance(mins, bool):
            raise ValueError("bad phase")
        if not 1 <= mins <= (720 if kind == "focus" else 120):
            raise ValueError("phase length out of range")
        phases.append({"kind": kind, "start": t, "end": t + mins * 60})
        t += mins * 60
    while phases and phases[-1]["kind"] == "break":
        phases.pop()
    if not phases or phases[0]["kind"] != "focus":
        raise ValueError("a session must start with focus")
    if phases[-1]["end"] - now > 24 * 3600:
        raise ValueError("session longer than 24 h")
    domains = req.get("domains", [])
    apps = req.get("apps", [])
    if not isinstance(domains, list) or not isinstance(apps, list) or len(domains) > 600 or len(apps) > 100:
        raise ValueError("bad lists")
    if not all(isinstance(d, str) and DOMAIN_RE.match(d) for d in domains):
        raise ValueError("bad domain")
    if not all(isinstance(a, str) and APP_RE.match(a) for a in apps):
        raise ValueError("bad app name")
    if not domains and not apps:
        raise ValueError("nothing to block")
    label = req.get("label", "")
    label = "".join(c for c in str(label) if c.isprintable()).strip()[:60]
    return {"version": 2, "start": now, "end": phases[-1]["end"], "label": label,
            "domains": sorted(set(domains)), "apps": sorted(set(apps)), "phases": phases}


def main():
    if os.geteuid() != 0 and not os.environ.get("MFOCUS_TEST"):
        sys.exit("must run as root")
    if len(sys.argv) != 2:
        sys.exit("usage: ctl_start.py '<json>'")
    now = int(time.time())
    try:
        state = build_state(json.loads(sys.argv[1]), now)
    except (ValueError, TypeError) as e:
        sys.exit(f"rejected: {e}")
    os.makedirs(DIR, exist_ok=True)
    try:
        with open(STATE) as f:
            old = json.load(f)
        if old.get("end", 0) > now:
            sys.exit("a session is already running")
    except (OSError, ValueError, AttributeError):
        pass
    fd, tmp = tempfile.mkstemp(dir=DIR, prefix=".mf-")
    with os.fdopen(fd, "w") as f:
        json.dump(state, f)
    os.chmod(tmp, 0o644)
    os.replace(tmp, STATE)
    if not os.environ.get("MFOCUS_TEST"):
        subprocess.run(["systemctl", "start", "mfocus.service"], check=False)
    print("started")


if __name__ == "__main__":
    main()
