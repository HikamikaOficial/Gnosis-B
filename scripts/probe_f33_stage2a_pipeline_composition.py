"""F-33 Stage-2A OS-REAL PROBE #2 — GovernedPipeline integration over F-17.

Where probe #1 qualified `TrustedExecutionPort.execute` directly over the real
Worker boundary, THIS probe begins ABOVE the seam and proves the INTEGRATED
execution path the governed pipeline actually uses:

    TaskEngine.cli_runner  ==  TrustedExecutionRunner   (the integration seam)
        -> TrustedExecutionPort.execute(DETERMINISTIC)
            -> real TrustedWindowsWorkerLauncher.launch(sealed LaunchSpec)
                -> F-17 bootstrap -> disposable non-admin Worker SID
                    -> deterministic Worker -> bounded result
        -> ExecutionResult   (governed success/failure)
    ...and TaskEngine.execute_task drives that same runner to a governed verdict.

It does NOT call `port.execute` directly. It creates disposable F-17-style
infrastructure and rolls everything back in a `finally` path. No production
account/service/ACL, no provider call, no F-17 change.

Run ELEVATED. There is deliberately NO `--keep`: this qualification always rolls
back.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import secrets
import shutil
import string
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
WORKER_NAME = "GnosisWkrF33b"                      # <= 20 chars, distinct from probe #1
PROBE_ROOT = Path(r"C:\ProgramData\Gnosis\F33PipeProbe")

LOG: list[str] = []


def say(text: str = "") -> None:
    print(text, flush=True)
    LOG.append(text)


def random_password() -> str:
    classes = (string.ascii_uppercase, string.ascii_lowercase, string.digits,
               "!#%&*+-=?@^_")
    required = [secrets.choice(group) for group in classes]
    alphabet = "".join(classes)
    chars = required + [secrets.choice(alphabet) for _ in range(24)]
    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return "".join(chars)


def icacls(*args: str) -> None:
    subprocess.run(["icacls", *args], capture_output=True, text=True,
                   encoding="utf-8", errors="replace", check=False)


def _force_rmtree(root: Path) -> None:
    """Remove a tree even when it contains git's read-only pack/object files,
    which a plain rmtree skips on Windows (leaving the root behind)."""
    import stat

    def _clear_readonly(func: Any, path: str, _exc: Any) -> None:
        os.chmod(path, stat.S_IWRITE)
        func(path)

    if not root.exists():
        return
    try:
        shutil.rmtree(root, onexc=_clear_readonly)
    except TypeError:  # Python < 3.12 fallback
        shutil.rmtree(root, onerror=_clear_readonly)


def elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001 - absence means not elevated
        return False


def _write_evidence(out_dir: Path, ev: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "f33_stage2a_pipeline.json").write_text(
        json.dumps(ev, indent=2, default=str), encoding="utf-8")
    (out_dir / "probe_log.txt").write_text("\n".join(LOG), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=None)
    ns = parser.parse_args()

    ev: dict[str, Any] = {}
    ok_overall = True
    blob_path: Path | None = None
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(ns.out) if ns.out else (REPO / "docs" / "evidence" /
                                           f"{ts}-f33-stage2a-pipeline")

    say("F-33 STAGE 2A — OS-REAL PIPELINE-THROUGH-PORT QUALIFICATION")
    say("=" * 78)
    ev["starting_head"] = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True,
        check=False).stdout.strip()
    ev["elevated"] = elevated()
    if not ev["elevated"]:
        say("NOT ELEVATED — refusing to touch OS state.")
        ev["blocked"] = "not elevated"
        _write_evidence(out_dir, ev)
        return 2

    tools = PROBE_ROOT / "tools"
    launch = PROBE_ROOT / "launch"
    secrets_dir = PROBE_ROOT / "secrets"
    work = PROBE_ROOT / "work"
    tools_src = tools / "src"
    runtime_dir = tools / "runtime"

    try:
        # ---- PROVISION (F-17-style, Design T) --------------------------------
        say("\nPROVISION — disposable infrastructure")
        say("-" * 78)
        if PROBE_ROOT.exists():
            subprocess.run(["icacls", str(PROBE_ROOT), "/reset", "/T", "/C", "/Q"],
                           capture_output=True, check=False)
            _force_rmtree(PROBE_ROOT)
        for path in (tools, launch, secrets_dir, work):
            path.mkdir(parents=True, exist_ok=True)

        say("   relocating runtime + full gnosis tree ...")
        shutil.copytree(Path(sys.base_prefix), runtime_dir, dirs_exist_ok=True)
        runtime = runtime_dir / "python.exe"
        shutil.copytree(REPO / "src" / "gnosis", tools_src / "gnosis",
                        dirs_exist_ok=True)

        sys.path.insert(0, str(tools_src))
        import getpass

        from gnosis.director.execution import TrustedExecutionPort
        from gnosis.director.trusted_runner import (
            TrustedExecutionRunner,
            deterministic_cassette_source,
        )
        from gnosis.kernel.engine import TaskEngine
        from gnosis.kernel.run_store import RunStore
        from gnosis.kernel.state_machine import TaskState
        from gnosis.kernel.verification import CommandVerifier
        from gnosis.provision import winapi
        from gnosis.trust.worker_launcher import (
            TrustedWindowsWorkerLauncher,
            WorkerAccount,
            protect_worker_secret,
        )
        director_sid = winapi.resolve_sid(getpass.getuser())
        say(f"   creating disposable non-admin account {WORKER_NAME} ...")
        password = random_password()
        if winapi.account_exists(WORKER_NAME):
            winapi.delete_local_account(WORKER_NAME)
        winapi.create_local_account(
            WORKER_NAME, password, "GNOSIS F-33 Stage-2A pipeline probe")
        worker_sid = winapi.resolve_sid(WORKER_NAME)
        ev["worker_sid"] = worker_sid
        ev["director_sid"] = director_sid
        say(f"   worker SID: {worker_sid}")

        blob_path = secrets_dir / "worker.dpapi"
        blob_path.write_bytes(protect_worker_secret(password))
        password = ""

        for path in (tools, launch):
            icacls(str(path), "/inheritance:r")
            icacls(str(path), "/grant:r", "*S-1-5-32-544:(OI)(CI)F",
                   "*S-1-5-18:(OI)(CI)F", f"*{worker_sid}:(OI)(CI)(RX)")
        icacls(str(secrets_dir), "/inheritance:r")
        icacls(str(secrets_dir), "/grant:r", "*S-1-5-32-544:(OI)(CI)F",
               "*S-1-5-18:(OI)(CI)F")
        icacls(str(work), "/inheritance:r")
        icacls(str(work), "/grant:r", "*S-1-5-32-544:(OI)(CI)F",
               "*S-1-5-18:(OI)(CI)F", f"*{worker_sid}:(OI)(CI)M")

        # ---- BUILD THE INTEGRATED SEAM (engine.cli_runner = trusted runner) --
        say("\nCOMPOSE — TaskEngine.cli_runner = TrustedExecutionRunner")
        say("-" * 78)
        launcher = TrustedWindowsWorkerLauncher(
            account=WorkerAccount(username=WORKER_NAME, domain=".",
                                  expected_sid=worker_sid,
                                  expected_integrity="Medium"),
            credential_blob_path=blob_path, launch_root=launch,
            runtime=runtime, director_env=dict(os.environ))
        port = TrustedExecutionPort(launcher=launcher, python_executable=runtime)
        runner = TrustedExecutionRunner(port, workspace=work)
        run_store = RunStore(work / "runs")
        engine = TaskEngine(run_store=run_store, cli_runner=runner)
        ev["engine_cli_runner_is_trusted_runner"] = (
            engine.cli_runner is runner)
        ev["integrated_path"] = (
            "TaskEngine.cli_runner(TrustedExecutionRunner).run -> "
            "TrustedExecutionPort.execute(DETERMINISTIC) -> "
            "TrustedWindowsWorkerLauncher.launch -> Worker")

        checks: list[tuple[str, bool, str]] = []

        def check(name: str, cond: bool, detail: str = "") -> None:
            checks.append((name, bool(cond), detail))
            say(f"   [{'PASS' if cond else 'FAIL'}] {name}"
                + (f"  ({detail})" if detail else ""))

        check("engine.cli_runner IS the trusted runner (integrated seam)",
              engine.cli_runner is runner)

        # ---- (1) DRIVE THE INTEGRATED RUNNER OVER THE REAL BOUNDARY ----------
        say("\nRUN #1 — engine.cli_runner.run() over the REAL Worker boundary")
        say("-" * 78)
        result = engine.cli_runner.run(
            prompt="governed-implementer-work",
            cwd=work, stdout_path=work / "impl.out", stderr_path=work / "impl.err",
            timeout_s=180.0)
        li = result.launch or {}
        ev["run1_succeeded"] = result.succeeded
        ev["run1_observed_sid"] = li.get("observed_sid")
        ev["run1_is_admin"] = li.get("is_administrator")
        ev["run1_contained"] = li.get("contained_in_job")
        ev["run1_result_schema"] = (result.parsed_json or {}).get("schema")
        ev["run1_provider_calls"] = (result.parsed_json or {}).get("provider_calls")
        check("integrated runner run succeeded", result.succeeded)
        check("observed SID == disposable worker SID",
              li.get("observed_sid") == worker_sid, str(li.get("observed_sid")))
        check("worker SID != director SID",
              worker_sid != director_sid, f"dir={director_sid}")
        check("worker non-admin", li.get("is_administrator") is False)
        check("worker contained in job", li.get("contained_in_job") is True)
        check("provider calls == 0", ev["run1_provider_calls"] == 0)

        # ---- (2) DRIVE THE FULL GOVERNED PATH: engine.execute_task -----------
        say("\nRUN #2 — engine.execute_task() governed verdict via the seam")
        say("-" * 78)
        gitrepo = work / "repo"
        gitrepo.mkdir(parents=True, exist_ok=True)
        for cmd in (["git", "init"], ["git", "config", "user.email", "e@x.com"],
                    ["git", "config", "user.name", "T"]):
            subprocess.run(cmd, cwd=gitrepo, capture_output=True, check=False)
        (gitrepo / "code.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=gitrepo, capture_output=True, check=False)
        subprocess.run(["git", "commit", "-m", "init"], cwd=gitrepo,
                       capture_output=True, check=False)
        verifier = CommandVerifier("check", [str(runtime), "-c", "raise SystemExit(0)"])
        outcome = engine.execute_task(
            task_id="F33B-1", objective="pipeline demo",
            prompt="governed-implementer-work", repo_path=gitrepo, verifier=verifier)
        ev["run2_task_state"] = str(outcome.final_task_state)
        ev["run2_run_ids"] = len(outcome.run_ids)
        check("governed execute_task reached COMPLETED via trusted seam",
              outcome.final_task_state == TaskState.COMPLETED,
              ev["run2_task_state"])

        # ---- (3) OS-REAL NEGATIVE THROUGH THE INTEGRATED SEAM ----------------
        say("\nRUN #3 — integrated seam propagates a REAL worker failure")
        say("-" * 78)

        def _bad_source(_prompt: str) -> bytes:
            # A schema the closed deterministic Worker rejects -> exit 13.
            return json.dumps({"schema": "gnosis.bad.v1", "turns": []}).encode("utf-8")

        neg_runner = TrustedExecutionRunner(
            port, cassette_source=_bad_source, workspace=work)
        neg = neg_runner.run(prompt="x", cwd=work,
                             stdout_path=work / "neg.out",
                             stderr_path=work / "neg.err", timeout_s=180.0)
        ev["run3_succeeded"] = neg.succeeded
        ev["run3_launch_is_none"] = neg.launch is None
        check("real worker failure -> integrated runner FAILED (fail closed)",
              (neg.succeeded is False) and (neg.launch is None))

        # sanity: the default deterministic source really is the closed schema.
        ev["default_cassette_is_closed"] = (
            set(json.loads(deterministic_cassette_source("z"))) == {"schema", "turns"})

        ev["checks"] = [{"name": n, "pass": p, "detail": d} for n, p, d in checks]
        ok_overall = all(p for _, p, _ in checks)
        ev["pipeline_composition"] = "PASS" if ok_overall else "FAIL"

        diff = subprocess.run(["git", "diff", "--stat", "--", "src/gnosis/trust"],
                              cwd=REPO, capture_output=True, text=True,
                              check=False).stdout.strip()
        ev["f17_impl_diff"] = diff or "NONE"
        say(f"\n   F-17 implementation diff: {ev['f17_impl_diff']}")

    except Exception as exc:  # noqa: BLE001 - probe reports failures as data
        ok_overall = False
        ev["exception"] = f"{type(exc).__name__}: {str(exc)[:400]}"
        ev["pipeline_composition"] = "FAIL"
        say(f"\nPROBE EXCEPTION: {ev['exception']}")
    finally:
        say("\nROLLBACK")
        say("-" * 78)
        rb: dict[str, Any] = {}
        try:
            kill = ("Get-CimInstance Win32_Process | Where-Object { "
                    f"$_.GetOwner().User -eq '{WORKER_NAME}' }} | ForEach-Object "
                    "{ Stop-Process -Id $_.ProcessId -Force "
                    "-ErrorAction SilentlyContinue }")
            subprocess.run(["powershell", "-NoProfile", "-Command", kill],
                           capture_output=True, check=False)
            try:
                from gnosis.provision import winapi as _wi
                status = _wi.delete_local_account(WORKER_NAME)
            except Exception:  # noqa: BLE001 - fall back to net user
                status = int(subprocess.run(["net", "user", WORKER_NAME, "/delete"],
                                            capture_output=True, check=False).returncode)
            rb["netuserdel_status"] = status
            drop = ("Get-CimInstance Win32_UserProfile | Where-Object { "
                    f"$_.LocalPath -like '*{WORKER_NAME}*' }} | Remove-CimInstance "
                    "-ErrorAction SilentlyContinue")
            subprocess.run(["powershell", "-NoProfile", "-Command", drop],
                           capture_output=True, check=False)
            profile = Path(r"C:\Users") / WORKER_NAME
            if profile.exists():
                _force_rmtree(profile)
            rb["profile_removed"] = not profile.exists()
            if PROBE_ROOT.exists():
                subprocess.run(["icacls", str(PROBE_ROOT), "/reset", "/T", "/C", "/Q"],
                               capture_output=True, check=False)
                _force_rmtree(PROBE_ROOT)
            rb["probe_root_removed"] = not PROBE_ROOT.exists()
            residual = subprocess.run(["net", "user", WORKER_NAME],
                                      capture_output=True, text=True,
                                      encoding="utf-8", errors="replace", check=False)
            rb["account_absent"] = residual.returncode != 0
            rb["dpapi_blob_absent"] = blob_path is None or not blob_path.exists()
            rb["rollback"] = ("PASS" if (rb.get("account_absent")
                              and rb.get("probe_root_removed")
                              and rb.get("dpapi_blob_absent")) else "FAIL")
        except Exception as exc:  # noqa: BLE001
            rb["rollback"] = "FAIL"
            rb["rollback_exception"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        for k, v in rb.items():
            say(f"   {k}: {v}")
        ev["rollback"] = rb
        _write_evidence(out_dir, ev)
        say(f"\nEvidence bundle: {out_dir}")

    say("\n" + "=" * 78)
    say(f"PIPELINE COMPOSITION: {ev.get('pipeline_composition')}")
    say(f"ROLLBACK: {ev.get('rollback', {}).get('rollback')}")
    return 0 if (ok_overall and ev.get("rollback", {}).get("rollback") == "PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
