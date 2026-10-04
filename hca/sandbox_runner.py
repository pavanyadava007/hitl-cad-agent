"""Child-process entry point that executes one LLM-written CadQuery script.

Usage: python sandbox_runner.py SCRIPT OUT_BREP EVENTS_JSON JAIL

The audit hook only *records* file writes, network and process events raised
while the agent's code runs (PEP 578); enforcement is done by the parent
(AST allowlist) and the OS (network namespace, rlimits).
"""

import json
import os
import sys

WATCH = ("open", "socket.connect", "socket.getaddrinfo", "subprocess.Popen", "os.system", "os.exec",
         "os.posix_spawn", "os.spawn", "os.fork", "os.remove", "os.rename", "os.mkdir", "urllib.Request",
         "shutil.copyfile", "shutil.rmtree")
_events = []
_recording = [False]


def _hook(event, args):
    if not _recording[0] or not event.startswith(WATCH):
        return
    if event == "open":
        path, mode, flags = (list(args) + [None, None, None])[:3]
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT))
        if not writing or not isinstance(path, (str, bytes, os.PathLike)):
            return
        _events.append({"event": "file_write", "target": os.path.abspath(os.fsdecode(path))})
        return
    _events.append({"event": event, "target": repr(args)[:300]})


def main() -> int:
    script, out_brep, events_path, jail = sys.argv[1:5]
    import cadquery as cq  # import before recording starts

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
