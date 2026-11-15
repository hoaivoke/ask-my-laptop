"""Runs Python / Lean code for the AI's tools inside a strict macOS sandbox.

The sandbox (written to runtime/exec.sb) blocks:
  - all network access
  - reading anything under /Users except the tools folder (and the Python install it uses)
  - writing anywhere except a fresh scratch folder for this run
  - launching programs other than the Python / Lean binaries
  - Apple Events, clipboard and keychain access
and the run is killed after a time limit or if it uses too much memory.
"""

import json
import os
import resource
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNTIME = HERE / "runtime"
TOOLS = RUNTIME / "tools"
JOBS = RUNTIME / "jobs"
PY = TOOLS / "py" / "bin" / "python"
ELAN = TOOLS / "elan"
MATHPROJ = TOOLS / "mathproj"
PROFILE = RUNTIME / "exec.sb"
INSTALL_PROFILE = RUNTIME / "install.sb"
UV = TOOLS / "bin" / "uv"
UV_CACHE = TOOLS / "uv-cache"
INSTALLED = TOOLS / "installed.json"     # the list of packages the AI added, and why

BASE_PACKAGES = ["numpy", "scipy", "sympy", "mpmath", "networkx", "pandas", "matplotlib", "z3-solver"]
MAX_TOOLS_MB = 4000                      # stop auto-installing once the Python tools folder is this big
MAX_INSTALLS_PER_DAY = 30
INSTALL_SECONDS = 240

LIMITS = {
    "python": {"seconds": 60, "mem_mb": 3000},
    "lean": {"seconds": 300, "mem_mb": 7000},
}
MAX_OUTPUT = 12000

_slots = threading.BoundedSemaphore(2)
_lean_env = None


def q(p):
    return '"%s"' % str(p).replace("\\", "\\\\").replace('"', '\\"')


def _profile(network, writable):
    home = str(Path.home())
    readable = [TOOLS]
    exec_ok = [TOOLS]
    if PY.exists():
        # the real Python install (managed by uv); allow its whole folder so the
        # chain of symlinks (py/bin/python -> cpython-3.12-... -> cpython-3.12.x-...) resolves
        real = Path(os.path.realpath(PY))
        base = real.parent.parent.parent if real.parent.parent.parent.name == "python" else real.parent.parent
        readable.append(base)
        exec_ok.append(base)
    lines = [
        "(version 1)",
        "(allow default)",
        "(deny network*)",
        "(deny file-read* (subpath \"/Users\") (subpath \"/Volumes\") (subpath \"/private/tmp\") (subpath \"/private/var/folders\"))",
        "(allow file-read* (literal \"/Users\") (literal %s))" % q(home),
        "(deny file-write* (subpath \"/\"))",
        "(allow file-write* (literal \"/dev/null\") (literal \"/dev/stdout\") (literal \"/dev/stderr\") (literal \"/dev/tty\"))",
        "(deny process-exec)",
        "(deny appleevent-send)",
        "(deny mach-lookup (global-name \"com.apple.pasteboard.1\") (global-name \"com.apple.SecurityServer\")"
        " (global-name \"com.apple.securityd.xpc\") (global-name \"com.apple.coreservices.launchservicesd\"))",
    ]
    if network:   # installer only: HTTPS out + DNS, nothing else
        lines += ["(allow network-outbound (remote tcp \"*:443\"))",
                  "(allow network-outbound (literal \"/private/var/run/mDNSResponder\"))",
                  "(allow system-socket)"]
    # parent folders: stat only, so paths can be resolved
    for p in readable:
        for parent in Path(p).parents:
            if not str(parent).startswith(home + "/"):
                break
            lines.append("(allow file-read-metadata (literal %s))" % q(parent))
    for p in readable:
        lines.append("(allow file-read* (subpath %s))" % q(p))
    for p in exec_ok:
        lines.append("(allow process-exec (subpath %s))" % q(p))
    for p in writable:
        lines.append("(allow file-read* file-write* (subpath %s))" % q(p))
    return "\n".join(lines) + "\n"


def write_profile():
    JOBS.mkdir(parents=True, exist_ok=True)
    UV_CACHE.mkdir(parents=True, exist_ok=True)
    src_uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
    if not UV.exists() and os.path.exists(src_uv):
        UV.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_uv, UV)       # keep the installer inside the tools folder
    PROFILE.write_text(_profile(network=False, writable=[JOBS]))
    INSTALL_PROFILE.write_text(_profile(network=True, writable=[JOBS, TOOLS / "py", UV_CACHE]))


def lean_env():
    """Ask lake (once, outside the sandbox) where Lean and Mathlib's compiled files are."""
    global _lean_env
    if _lean_env is None:
        env = dict(os.environ, ELAN_HOME=str(ELAN), PATH="%s/bin:/usr/bin:/bin" % ELAN)
        run = lambda *a: subprocess.run(list(a), cwd=MATHPROJ, env=env, capture_output=True,
                                        text=True, timeout=120).stdout.strip()
        _lean_env = {"LEAN_PATH": run("lake", "env", "printenv", "LEAN_PATH"),
                     "LEAN_BIN": run("elan", "which", "lean")}
    return _lean_env


def available():
    return {"python": PY.exists(), "lean": (MATHPROJ / ".lake").exists()}


def _limits(seconds):
    def apply():
        os.setsid()
        resource.setrlimit(resource.RLIMIT_CPU, (seconds + 5, seconds + 5))
        resource.setrlimit(resource.RLIMIT_FSIZE, (64 << 20, 64 << 20))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    return apply


def _rss_mb(pgid):
    try:
        out = subprocess.run(["ps", "-o", "rss=", "-g", str(pgid)], capture_output=True, text=True).stdout
        return sum(int(x) for x in out.split()) // 1024
    except Exception:
        return 0


def run_code(lang, code):
    if lang not in LIMITS:
        return {"stdout": "", "stderr": "unknown language", "exit_code": -1}
    if not available()[lang]:
        return {"stdout": "", "stderr": "%s is not installed on this server yet" % lang, "exit_code": -1}
    lim = LIMITS[lang]
    if not _slots.acquire(timeout=120):
        return {"stdout": "", "stderr": "busy: too many code runs at once, try again", "exit_code": -1}
    job = Path(tempfile.mkdtemp(prefix="job-", dir=JOBS))
    try:
        env = {"PATH": "/usr/bin:/bin", "HOME": str(job), "TMPDIR": str(job), "LANG": "en_US.UTF-8",
               "MPLBACKEND": "Agg", "MPLCONFIGDIR": str(job), "PYTHONDONTWRITEBYTECODE": "1"}
        if lang == "python":
            (job / "main.py").write_text(code)
            cmd = [str(PY), "-I", "main.py"]
        else:
            (job / "Main.lean").write_text(code)
            le = lean_env()
            env["LEAN_PATH"] = le["LEAN_PATH"]
            cmd = [le["LEAN_BIN"], "Main.lean"]
        proc = subprocess.Popen(["/usr/bin/sandbox-exec", "-f", str(PROFILE)] + cmd, cwd=str(job),
                                env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, errors="replace",
                                preexec_fn=_limits(lim["seconds"]))
        flags = {"timed_out": False, "killed_for_memory": False}

        def watch():
            start = time.time()
            while proc.poll() is None:
                if time.time() - start > lim["seconds"]:
                    flags["timed_out"] = True
                elif _rss_mb(proc.pid) > lim["mem_mb"]:
                    flags["killed_for_memory"] = True
                else:
                    time.sleep(0.5)
                    continue
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                return

        w = threading.Thread(target=watch, daemon=True)
        w.start()
        out, err = proc.communicate()
        w.join(timeout=2)
        clip = lambda s: s if len(s) <= MAX_OUTPUT else s[:MAX_OUTPUT] + "\n...[output cut off]"
        return dict(flags, stdout=clip(out), stderr=clip(err), exit_code=proc.returncode)
    finally:
        _slots.release()
        shutil.rmtree(job, ignore_errors=True)


# ------------------------------------------------------- auto-install ---
import re
from datetime import datetime

_install_lock = threading.Lock()
NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?(?:==[A-Za-z0-9.+!-]{1,40})?$")


def _load_installed():
    try:
        return json.loads(INSTALLED.read_text())
    except (FileNotFoundError, ValueError):
        return []


def _dir_mb(path):
    out = subprocess.run(["du", "-sm", str(path)], capture_output=True, text=True).stdout
    return int(out.split()[0]) if out else 0


def _versions():
    """{normalized name: version} for everything in the tools Python."""
    out = subprocess.run([str(UV), "pip", "list", "--format", "json", "--python", str(PY), "--no-config"],
                         capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "UV_CACHE_DIR": str(UV_CACHE)})
    try:
        return {re.sub(r"[-_.]+", "-", x["name"]).lower(): x["version"] for x in json.loads(out.stdout)}
    except ValueError:
        return {}


def tool_list():
    """Text for the AI: what's installed beyond the base set."""
    extra = sorted({e["package"] for e in _load_installed()})
    return ", ".join(BASE_PACKAGES + extra)


def install_packages(names, reason="", asked_by=""):
    names = [str(n).strip() for n in (names or []) if str(n).strip()]
    if not names or len(names) > 5:
        return {"ok": False, "message": "Give 1 to 5 package names."}
    bad = [n for n in names if not NAME_RE.match(n)]
    if bad:
        return {"ok": False, "message": "Not allowed (plain PyPI names only, optional ==version): %s" % bad}
    if not UV.exists() or not PY.exists():
        return {"ok": False, "message": "The installer isn't set up on this server."}
    today = datetime.now().strftime("%Y-%m-%d")
    log = _load_installed()
    if sum(1 for e in log if e.get("date", "").startswith(today)) >= MAX_INSTALLS_PER_DAY:
        return {"ok": False, "message": "Daily install limit reached. Ask the owner to add it."}
    if _dir_mb(TOOLS / "py") > MAX_TOOLS_MB:
        return {"ok": False, "message": "The tools folder is full. Ask the owner to add it."}
    if not _install_lock.acquire(timeout=INSTALL_SECONDS):
        return {"ok": False, "message": "Another install is running. Try again shortly."}
    job = Path(tempfile.mkdtemp(prefix="install-", dir=JOBS))
    try:
        before = _versions()
        env = {"PATH": "/usr/bin:/bin", "HOME": str(job), "TMPDIR": str(job), "UV_CACHE_DIR": str(UV_CACHE),
               "UV_NO_CONFIG": "1", "UV_PYTHON_DOWNLOADS": "never", "SSL_CERT_FILE": "/etc/ssl/cert.pem"}
        cmd = ["/usr/bin/sandbox-exec", "-f", str(INSTALL_PROFILE), str(UV), "pip", "install",
               "--python", str(PY), "--no-build", "--no-config", "--index-url", "https://pypi.org/simple"] + names
        try:
            r = subprocess.run(cmd, cwd=str(job), env=env, capture_output=True, text=True, timeout=INSTALL_SECONDS)
            out, code = (r.stdout + r.stderr)[-4000:], r.returncode
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "The install took too long and was stopped."}
        if code != 0:
            return {"ok": False, "message": "Install failed (only prebuilt wheels are allowed):\n" + out}
        after = _versions()
        added = {k: v for k, v in after.items() if before.get(k) != v}
        now = datetime.now().isoformat(timespec="seconds")
        for n in names:
            key = re.sub(r"[-_.]+", "-", n.split("==")[0]).lower()
            log.append({"package": key, "version": after.get(key, "?"), "date": now,
                        "reason": str(reason)[:300], "asked_by": str(asked_by)[:300],
                        "also_installed": sorted("%s==%s" % kv for kv in added.items() if kv[0] != key)})
        INSTALLED.write_text(json.dumps(log, indent=1))
        return {"ok": True, "installed": {k: after.get(re.sub(r"[-_.]+", "-", k.split("==")[0]).lower())
                                          for k in names},
                "also_installed": sorted("%s==%s" % kv for kv in added.items()
                                         if kv[0] not in {re.sub(r"[-_.]+", "-", n.split("==")[0]).lower() for n in names}),
                "message": out[-1500:]}
    finally:
        _install_lock.release()
        shutil.rmtree(job, ignore_errors=True)


if __name__ == "__main__":   # quick manual test: python3 executor.py python 'print(1)'
    import sys
    write_profile()
    if sys.argv[1] == "install":
        print(json.dumps(install_packages(sys.argv[2:], "manual test", "command line"), indent=1))
    else:
        print(json.dumps(run_code(sys.argv[1], sys.argv[2]), indent=1))
