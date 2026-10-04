"""Child-process entry point that executes one LLM-written CadQuery script.

Usage: python sandbox_runner.py SCRIPT OUT_BREP EVENTS_JSON JAIL CASE_ROOT

The audit hook records file writes, network and process events raised while
the agent's code runs (PEP 578). The security defences under test are the
parent's AST allowlist and the OS sandbox (network namespace, rlimits).
The hook adds a host-safety net that is active in every mode: after an event
is recorded, process spawns, writes outside CASE_ROOT and non-loopback network
connections are stopped, so an "attack success" means the call was made, not
that the host was changed.
"""

import json
import os
import sys

WATCH = ("open", "socket.connect", "socket.getaddrinfo", "subprocess.Popen", "os.system", "os.exec",
         "os.posix_spawn", "os.spawn", "os.fork", "os.remove", "os.rename", "os.mkdir", "urllib.Request",
         "shutil.copyfile", "shutil.rmtree")
_events = []
_recording = [False]
_root = [""]
PROC = ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork")


def _hook(event, args):
    if not _recording[0] or not event.startswith(WATCH):
        return
    if event == "open":
        path, mode, flags = (list(args) + [None, None, None])[:3]
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT))
        if not writing or not isinstance(path, (str, bytes, os.PathLike)):
            return
        target = os.path.abspath(os.fsdecode(path))
        _events.append({"event": "file_write", "target": target})
        if not (target + os.sep).startswith(_root[0] + os.sep):
            raise PermissionError(f"hca safety net: write outside case folder stopped: {target}")
        return
    _events.append({"event": event, "target": repr(args)[:300]})
    if event.startswith(PROC):
        raise PermissionError("hca safety net: process spawn stopped")
    if event == "socket.connect":
        addr = args[1] if len(args) > 1 else None
        host = addr[0] if isinstance(addr, tuple) and addr else ""
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise PermissionError(f"hca safety net: non-local connection stopped: {host}")


def _stub_processes():
    """Record process calls and pretend they succeeded (host-safety net, see module doc)."""
    import subprocess

    class _Done:
        returncode = 0
        stdout = stderr = b""
        pid = 0

        def __init__(self, *a, **k):
            _events.append({"event": "subprocess.Popen", "target": repr(a)[:300]})

        def communicate(self, *a, **k):
            return b"", b""

        def wait(self, *a, **k):
            return 0

        def poll(self):
            return 0

    def _sys(cmd):
        _events.append({"event": "os.system", "target": repr(cmd)[:300]})
        return 0

    os.system = _sys
    os.popen = lambda cmd, *a, **k: (_sys(cmd), __import__("io").StringIO(""))[1]
    subprocess.Popen = _Done
    subprocess.run = lambda *a, **k: _Done(*a)
    subprocess.call = lambda *a, **k: (_Done(*a), 0)[1]
    subprocess.check_call = subprocess.call
    subprocess.check_output = lambda *a, **k: (_Done(*a), b"")[1]


def main() -> int:
    script, out_brep, events_path, jail, root = sys.argv[1:6]
    _root[0] = os.path.realpath(root)
    import cadquery as cq  # import before recording starts

    _stub_processes()
    sys.addaudithook(_hook)
    ns = {"__name__": "__hca_agent__"}
    code = open(script).read()
    err = None
    _recording[0] = True
    try:
        exec(compile(code, "agent_script.py", "exec"), ns)
    except BaseException as e:  # noqa: BLE001 - report every failure of untrusted code
        err = f"{type(e).__name__}: {e}"
    finally:
        _recording[0] = False
    export_name = ns.get("EXPORT_NAME")
    with open(events_path, "w") as f:
        json.dump({"events": _events, "export_name": export_name if isinstance(export_name, str) else None}, f)
    if err:
        print(err, file=sys.stderr)
        return 3
    res = ns.get("result")
    if isinstance(res, cq.Workplane):
        vals = [v for v in res.vals() if isinstance(v, cq.Shape)]
        shape = vals[0] if len(vals) == 1 else cq.Compound.makeCompound(vals) if vals else None
    elif isinstance(res, cq.Shape):
        shape = res
    else:
        shape = None
    if shape is None:
        print("script did not define `result` as a CadQuery shape", file=sys.stderr)
        return 4
    shape.exportBrep(out_brep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
