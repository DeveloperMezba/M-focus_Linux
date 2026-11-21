"""FocusGuard (Windows) - shared, Qt-free logic.

Three roles, all in one exe:
  FocusGuard.exe                         -> the GUI (normal user)
  FocusGuard.exe --ctl start <min> <d..> -> run elevated (UAC) by the GUI; starts a locked session
  FocusGuard.exe --enforcer              -> run as SYSTEM by a Task Scheduler task; keeps the
                                            hosts-file block applied until the session ends
"""
import ctypes
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

APP = "FocusGuard"
TASK = "FocusGuardEnforcer"
DATA = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / APP
INSTALL = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / APP
STATE = DATA / "state.json"
HIST = DATA / "history.json"
ERRFILE = DATA / "ctl_error.txt"
LOG = DATA / "enforcer.log"
HOSTS = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"

BEGIN = "# >>> FOCUSGUARD BEGIN >>>"
END = "# <<< FOCUSGUARD END <<<"
DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9-]{1,63}\.)+[a-z]{2,63}$")
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


# ---------------------------------------------------------------- helpers
def read_json(path, default):
    for _ in range(4):  # the enforcer may be replacing the file right now
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return default
        except Exception:
            time.sleep(0.05)
    return default


def write_json(path, data):
    fd, tmp = tempfile.mkstemp(dir=str(DATA))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, str(path))


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S ") + str(msg) + "\n")
    except Exception:
        pass


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run(cmd, timeout=30):
    return subprocess.run(cmd, capture_output=True, timeout=timeout,
                          creationflags=NO_WINDOW)


# ---------------------------------------------------------------- hosts file
def read_hosts():
    with open(HOSTS, "rb") as f:
        raw = f.read().decode("utf-8", errors="surrogateescape")
    return "\n".join(raw.splitlines()) + "\n"


def strip_block(text):
    out, skip = [], False
    for line in text.splitlines():
        s = line.strip()
        if s == BEGIN:
            skip = True
            continue
        if s == END:
            skip = False
            continue
        if not skip:
            out.append(line)
    return "\n".join(out).rstrip("\n") + "\n"


def build_block(domains):
    lines = [BEGIN]
    for d in sorted(set(domains)):
        for host in sorted({d, "www." + d}):
            lines.append("0.0.0.0 " + host)
            lines.append("::1 " + host)
    lines.append(END)
    return "\n".join(lines) + "\n"


def write_hosts(text):
    try:
        os.chmod(str(HOSTS), stat.S_IWRITE | stat.S_IREAD)  # clear read-only flag
    except Exception:
        pass
    data = text.replace("\n", "\r\n").encode("utf-8", errors="surrogateescape")
    with open(HOSTS, "wb") as f:
        f.write(data)
    try:
        run(["ipconfig", "/flushdns"], timeout=10)
    except Exception:
        pass


# ---------------------------------------------------------------- enforcer (SYSTEM)
def protect_process(pid=None):
    """Deny terminate / suspend / inject / change-permissions on a process to everybody,
    so Task Manager's "End task" says "Access is denied". (A debugger-level tool run by an
    admin can still get around this - nothing on Windows can stop a determined admin.)"""
    try:
        adv, k32 = ctypes.windll.advapi32, ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        h = k32.GetCurrentProcess() if pid is None else k32.OpenProcess(0x40000, False, pid)  # WRITE_DAC
        if not h:
            return False
        psd = ctypes.c_void_p()
        # deny TERMINATE|CREATE_THREAD|VM_OPERATION|VM_WRITE|SUSPEND_RESUME|WRITE_DAC|WRITE_OWNER
        sddl = "D:(D;;0xC082B;;;WD)(A;;0x1FFFFF;;;WD)"
        ok = adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(psd), None)
        if not ok:
            return False
        adv.SetKernelObjectSecurity.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]
        ok = adv.SetKernelObjectSecurity(h, 0x4, psd)  # DACL_SECURITY_INFORMATION
        if pid is not None:
            k32.CloseHandle(ctypes.c_void_p(h))
        return bool(ok)
    except Exception as e:
        log("protect_process failed: %r" % (e,))
        return False


def _self_command():
    return '"%s" --enforcer' % sys.executable if getattr(sys, "frozen", False) else None


def finish(state):
    hist = read_json(HIST, [])
    hist.append({
        "date": datetime.fromtimestamp(state["start"]).strftime("%Y-%m-%d"),
        "minutes": state["minutes"],
    })
    write_json(HIST, hist[-2000:])
    try:
        os.remove(str(STATE))
    except FileNotFoundError:
        pass
    # session over: drop the once-a-minute watchdog trigger again (keep only the boot trigger)
    cmd = _self_command()
    if cmd:
        try:
            xml_path = DATA / "task.xml"
            with open(xml_path, "w", encoding="utf-16") as f:
                f.write(_task_xml(cmd, watchdog=False))
            run(["schtasks", "/Create", "/TN", TASK, "/XML", str(xml_path), "/F"])
        except Exception as e:
            log("could not reset task: %r" % (e,))


def tick():
    state = read_json(STATE, None)
    text = read_hosts()
    if state and state.get("end", 0) > time.time():
        desired = strip_block(text) + "\n" + build_block(state["domains"])
        if desired != text:
            write_hosts(desired)
        return True
    if state:
        finish(state)
    if BEGIN in text:
        write_hosts(strip_block(text))
    return False


def enforcer_main():
    DATA.mkdir(parents=True, exist_ok=True)
    protect_process()
    if getattr(sys, "frozen", False):  # one-file exe: also protect the launcher parent process
        protect_process(os.getppid())
    while True:
        try:
            active = tick()
        except Exception as e:  # never drop the block because of an error
            log("enforcer error: %r" % (e,))
            active = True
        if not active:
            break  # no session: exit; the task starts again on next session / boot
        time.sleep(2)
    return 0


# ---------------------------------------------------------------- privileged start (admin)
def _lock_down_data_dir():
    """Only Administrators/SYSTEM may write to the data dir; everyone may read."""
    try:
        run(["icacls", str(DATA), "/inheritance:r",
             "/grant:r", "*S-1-5-18:(OI)(CI)F",
             "/grant:r", "*S-1-5-32-544:(OI)(CI)F",
             "/grant:r", "*S-1-5-32-545:(OI)(CI)RX"])
    except Exception as e:
        log("icacls failed: %r" % (e,))


def _install_copy():
    """Copy ourselves to Program Files (writable only by admins) so the SYSTEM task
    never runs a file that a normal user could swap out. Returns the task command line."""
    INSTALL.mkdir(parents=True, exist_ok=True)
    if getattr(sys, "frozen", False):
        src = Path(sys.executable)
        dst = INSTALL / "FocusGuard.exe"
        try:
            if not dst.exists() or dst.stat().st_size != src.stat().st_size \
                    or int(dst.stat().st_mtime) != int(src.stat().st_mtime):
                shutil.copy2(str(src), str(dst))
        except PermissionError:
            if not dst.exists():
                raise
        return '"%s" --enforcer' % dst
    # running from source (testing): copy the scripts next to each other
    here = Path(__file__).resolve().parent
    for name in ("fg_core.py", "main.py"):
        shutil.copy2(str(here / name), str(INSTALL / name))
    return '"%s" "%s" --enforcer' % (sys.executable, INSTALL / "main.py")


def _task_xml(command, watchdog=True):
    exe, _, args = command.partition('" ')
    exe = exe.lstrip('"')
    args = args.strip()
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # watchdog: every minute during a session, (re)start the enforcer if someone killed it.
    # "IgnoreNew" below makes this a no-op while the enforcer is already running.
    wd = ("""
    <TimeTrigger><StartBoundary>2024-01-01T00:00:00</StartBoundary>
      <Repetition><Interval>PT1M</Interval></Repetition><Enabled>true</Enabled></TimeTrigger>"""
          if watchdog else "")
    return """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>FocusGuard enforcer - keeps the site block active during a focus session.</Description></RegistrationInfo>
  <Triggers>
    <BootTrigger><Enabled>true</Enabled></BootTrigger>%s
  </Triggers>
  <Principals><Principal id="Author"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>6</Priority>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author"><Exec><Command>%s</Command><Arguments>%s</Arguments></Exec></Actions>
</Task>
""" % (wd, esc(exe), esc(args))


def _register_and_run_task(command):
    xml_path = DATA / "task.xml"
    with open(xml_path, "w", encoding="utf-16") as f:
        f.write(_task_xml(command))
    r = run(["schtasks", "/Create", "/TN", TASK, "/XML", str(xml_path), "/F"])
    if r.returncode != 0:
        raise RuntimeError("Could not create the scheduled task: "
                           + (r.stderr or r.stdout).decode("mbcs", "replace").strip())
    r = run(["schtasks", "/Run", "/TN", TASK])
    if r.returncode != 0:
        raise RuntimeError("Could not start the scheduled task: "
                           + (r.stderr or r.stdout).decode("mbcs", "replace").strip())


def ctl_start(minutes_arg, domain_args):
    if not is_admin():
        raise RuntimeError("must run as administrator")
    try:
        minutes = int(minutes_arg)
    except ValueError:
        raise RuntimeError("invalid minutes")
    if not 1 <= minutes <= 720:
        raise RuntimeError("minutes must be 1..720")
    domains = [d.lower() for d in domain_args]
    if not domains:
        raise RuntimeError("no domains given")
    for d in domains:
        if not DOMAIN_RE.match(d):
            raise RuntimeError("invalid domain: " + d)

    DATA.mkdir(parents=True, exist_ok=True)
    _lock_down_data_dir()
    cur = read_json(STATE, {})
    if cur.get("end", 0) > time.time():
        raise RuntimeError("a session is already active")

    command = _install_copy()
    now = time.time()
    write_json(STATE, {"start": now, "end": now + minutes * 60,
                       "minutes": minutes, "domains": sorted(set(domains))})
    try:
        _register_and_run_task(command)
    except Exception:
        try:
            os.remove(str(STATE))
        except FileNotFoundError:
            pass
        raise


def ctl_main(argv):
    """argv = ['start', minutes, domain, ...]. Exit code 0 ok, 1 error (message in ERRFILE)."""
    try:
        try:
            DATA.mkdir(parents=True, exist_ok=True)
            if ERRFILE.exists():
                os.remove(str(ERRFILE))
        except Exception:
            pass
        if len(argv) < 3 or argv[0] != "start":
            raise RuntimeError("usage: --ctl start <minutes> <domain...>")
        ctl_start(argv[1], argv[2:])
        return 0
    except Exception as e:
        try:
            ERRFILE.write_text(str(e), encoding="utf-8")
        except Exception:
            pass
        log("ctl error: %r" % (e,))
        return 1


# ---------------------------------------------------------------- UAC elevation (used by the GUI)
def run_elevated_and_wait(args, pump=None):
    """Re-launch this program with UAC elevation, wait for it, return its exit code.
    Returns None if the user cancelled the UAC prompt."""
    from ctypes import wintypes as wt

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wt.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wt.HWND),
            ("lpVerb", wt.LPCWSTR), ("lpFile", wt.LPCWSTR), ("lpParameters", wt.LPCWSTR),
            ("lpDirectory", wt.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wt.HINSTANCE),
            ("lpIDList", ctypes.c_void_p), ("lpClass", wt.LPCWSTR), ("hkeyClass", wt.HKEY),
            ("dwHotKey", wt.DWORD), ("hIconOrMonitor", wt.HANDLE), ("hProcess", wt.HANDLE),
        ]

    if getattr(sys, "frozen", False):
        exe, params = sys.executable, subprocess.list2cmdline(["--ctl"] + list(args))
    else:
        exe = sys.executable
        params = subprocess.list2cmdline([str(Path(__file__).resolve().parent / "main.py"),
                                          "--ctl"] + list(args))

    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = exe
    info.lpParameters = params
    info.nShow = 0  # SW_HIDE
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        return None  # cancelled (error 1223) or failed to launch
    k32 = ctypes.windll.kernel32
    while k32.WaitForSingleObject(info.hProcess, 100) == 0x102:  # WAIT_TIMEOUT
        if pump:
            pump()
    code = wt.DWORD()
    k32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    k32.CloseHandle(info.hProcess)
    return int(code.value)


def read_ctl_error():
    try:
        return ERRFILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
