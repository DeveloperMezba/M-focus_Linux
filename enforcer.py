#!/usr/bin/python3
"""M Focus enforcer (runs as root under systemd, only while a session is active).

Every 2 seconds it makes the system match the session in state.json:
  * during a *focus* phase: websites are blocked in /etc/hosts and the listed
    apps are closed;  during a *break* phase: everything is open again;
  * it counts the focused time it actually observed and writes it to history.json
    when a phase ends (suspended / powered-off time is not credited).
When the session is over it removes the block and exits.
"""
import json
import os
import signal
import subprocess
import tempfile
import time
from datetime import datetime

DIR = os.environ.get("MFOCUS_DIR", "/var/lib/mfocus")
HOSTS = os.environ.get("MFOCUS_HOSTS", "/etc/hosts")
PROC = os.environ.get("MFOCUS_PROC", "/proc")
STATE = os.path.join(DIR, "state.json")
HIST = os.path.join(DIR, "history.json")
BEGIN = "# >>> M FOCUS BEGIN >>>"
END = "# <<< M FOCUS END <<<"
PREFIXES = ("www.", "m.", "mobile.")
TESTING = bool(os.environ.get("MFOCUS_TEST"))


def read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_atomic(path, text):
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".mf-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json(path, data):
    write_atomic(path, json.dumps(data))


def strip_block(text):
    out, skip = [], False
    for line in text.splitlines():
        if line.strip() == BEGIN:
            skip = True
        elif line.strip() == END:
            skip = False
        elif not skip:
            out.append(line)
    return "\n".join(out).rstrip("\n") + "\n"


def build_block(domains):
    names = []
    for d in domains:
        names.append(d)
        if not d.startswith(PREFIXES):
            names += [p + d for p in PREFIXES]
    lines = [BEGIN]
    for n in dict.fromkeys(names):
        lines.append(f"0.0.0.0 {n}")
        lines.append(f":: {n}")
    lines.append(END)
    return "\n".join(lines) + "\n"


def write_hosts(text):
    write_atomic(HOSTS, text)
    if not TESTING:
        for cmd in (["resolvectl", "flush-caches"], ["nscd", "-i", "hosts"]):
            try:
                subprocess.run(cmd, capture_output=True, timeout=5)
            except Exception:
                pass


def kill_apps(apps, kill=os.kill):
    """SIGTERM every process whose name (/proc/PID/comm) is in `apps`."""
    want, killed = set(apps), []
    if not want:
        return killed
    try:
        pids = [p for p in os.listdir(PROC) if p.isdigit()]
    except OSError:
        return killed
    for pid in pids:
        if int(pid) == os.getpid():
            continue
        try:
            with open(f"{PROC}/{pid}/comm") as f:
                comm = f.read().strip()
        except OSError:
            continue
        if comm in want:
            try:
                kill(int(pid), signal.SIGTERM)
                killed.append(comm)
            except OSError:
                pass
    return killed


def current_phase(state, now):
    for i, ph in enumerate(state["phases"]):
        if ph["start"] <= now < ph["end"]:
            return i, ph
    return None, None


def record(state, j, now):
    p = state["phases"][j]
    minutes = int(round(state.get("acc", {}).get(str(j), 0.0) / 60))
    if minutes < 1:
        return
    hist = read_json(HIST, [])
    hist.append({"date": datetime.fromtimestamp(p["start"]).strftime("%Y-%m-%d"),
                 "minutes": minutes, "start": p["start"],
                 "end": min(p["end"], now), "label": state.get("label", "")})
    write_json(HIST, hist[-5000:])


class Enforcer:
    def __init__(self):
        self.last = time.time()
        self.n = 0
        self.key = None      # which session the in-memory counters belong to
        self.acc = {}        # observed focus seconds per phase index
        self.rec = []        # phases already written to history

    def tick(self, now=None, kill=os.kill):
        """One pass. Returns True while a session is still active."""
        now = time.time() if now is None else now
        dt = max(0.0, min(now - self.last, 5.0))
        self.last = now
        state = read_json(STATE, None)
        try:
            with open(HOSTS) as f:
                text = f.read()
        except OSError:
            text = ""
        if not isinstance(state, dict) or not isinstance(state.get("phases"), list):
            if BEGIN in text:
                write_hosts(strip_block(text))
            return False

        if state.get("start") != self.key:   # new session (or service restarted)
            self.key = state.get("start")
            self.acc = dict(state.get("acc", {}))
            self.rec = list(state.get("recorded", []))
        state["acc"], state["recorded"] = self.acc, self.rec
        i, ph = current_phase(state, now)
        blocking = bool(ph and ph["kind"] == "focus")
        dirty = False
        if blocking:
            self.acc[str(i)] = self.acc.get(str(i), 0.0) + dt
            self.n += 1
            dirty = self.n % 15 == 0          # flush progress every ~30 s
        for j, p in enumerate(state["phases"]):
            if p["kind"] == "focus" and p["end"] <= now and j not in self.rec:
                record(state, j, now)
                self.rec.append(j)
                dirty = True

        if blocking:
            want = strip_block(text) + "\n" + build_block(state.get("domains", []))
        else:
            want = strip_block(text) if BEGIN in text else text
        if want != text:
            write_hosts(want)
        if blocking:
            kill_apps(state.get("apps", []), kill)

        if state.get("end", 0) <= now:
            try:
                os.remove(STATE)
            except FileNotFoundError:
                pass
            return False
        if dirty:
            write_json(STATE, state)
        return True


def main():
    enf = Enforcer()
    while True:
        try:
            if not enf.tick():
                break
        except Exception as e:             # never die in the middle of a session
            print("tick failed:", e, flush=True)
        time.sleep(2)


if __name__ == "__main__":
    main()
