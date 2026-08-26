"""P2 trusted publisher entry point.

Usage:
    python main.py console <config.json>   # foreground, for local validation
    python main.py service <config.json>   # under the Windows SCM

Hardening: launched by ImagePath as `python.exe -I -S main.py ...` so PYTHON*
env, user-site, .pth and sitecustomize are all neutralized. sys.path[0] is pinned
to this file's own (worker-non-writable) directory; the CWD is never trusted.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Pin imports to the trusted root only; never trust CWD/argv-derived paths.
sys.path[:] = [str(HERE)] + [p for p in sys.path if p and Path(p).resolve() != Path.cwd()]

from trust import tokendump                       # noqa: E402
from trust.pipeserver import PipeServer           # noqa: E402
from trust.publisher import Publisher, recover    # noqa: E402


def make_logger(path: Path):
    def log(msg: str) -> None:
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(msg + "\n")
        except OSError:
            pass
    return log


def startup(cfg: dict, log) -> None:
    state = Path(cfg["trust_state_root"])
    state.mkdir(parents=True, exist_ok=True)
    (state / "anchors").mkdir(parents=True, exist_ok=True)
    (state / "runidentity").mkdir(parents=True, exist_ok=True)
    try:
        (state / "token-dump.json").write_text(
            json.dumps(tokendump.dump(), indent=2), encoding="utf-8")
        log("token dumped")
    except Exception as exc:  # noqa: BLE001
        log(f"token dump FAILED: {exc!r}")
    rec = recover(state / "anchors", log)
    log(f"recovery: {rec}")


def build_server(cfg: dict, log) -> PipeServer:
    pub = Publisher(cfg, log)
    return PipeServer(cfg["pipe_name"], cfg["pipe_sddl"], pub.handle, log)


def _breadcrumb(name: str, text: str) -> None:
    """Diagnostic: write a boot/crash marker next to the config, before anything
    that could fail silently under the SCM. Best-effort."""
    try:
        base = Path(sys.argv[2]).parent if len(sys.argv) > 2 else HERE
        (base / name).write_text(text, encoding="utf-8")
    except Exception:
        pass


def main() -> int:
    _breadcrumb("boot.txt", f"argv={sys.argv!r} exe={sys.executable} cwd={Path.cwd()}")
    if len(sys.argv) < 3:
        print("usage: main.py console|service <config.json>", file=sys.stderr)
        return 2
    mode, cfg_path = sys.argv[1], sys.argv[2]
    # utf-8-sig tolerates a BOM (PowerShell writers add one); still valid UTF-8.
    cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8-sig"))
    log = make_logger(Path(cfg["trust_state_root"]) / "publisher.log")
    log(f"=== start mode={mode} exe={sys.executable} isolated={sys.flags.isolated} "
        f"no_site={sys.flags.no_site} path0={sys.path[0]} ===")
    startup(cfg, log)
    srv = build_server(cfg, log)
    Path(cfg["trust_state_root"], "ready.flag").write_text("1", encoding="utf-8")

    if mode == "console":
        log("console: serving")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            srv.stop()
        return 0

    if mode == "service":
        from trust.scmhost import ServiceHost
        host = ServiceHost(cfg["service_name"],
                           on_start=lambda ev: srv.serve_forever(),
                           on_stop=srv.stop, log=log)
        host.run()
        return 0

    print(f"unknown mode {mode}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as _exc:  # noqa: BLE001
        import traceback
        _breadcrumb("crash.txt", traceback.format_exc())
        raise
