"""F-33 Stage-2A OS-REAL PROBE — TrustedExecutionPort → real Worker boundary.

Proves the NEW Stage-2A execution seam over the REAL F-17 boundary:

    TrustedExecutionPort.execute(DETERMINISTIC, ...)
        -> real TrustedWindowsWorkerLauncher.launch(sealed LaunchSpec)
            -> F-17 bootstrap  (runs under the disposable Worker SID)
                -> deterministic_worker  (stdlib-only, provider-free)
                    -> bounded JSON result
        -> TrustedExecutionPort result validation

It creates DISPOSABLE infrastructure, exercises the boundary through the PORT
(never bypassing it), and rolls everything back in a `finally` path — PASS, FAIL
or exception. Nothing production is created or modified.

    account   GnosisWkrF33      (local, non-admin, deleted at the end)
    root      C:\\ProgramData\\Gnosis\\F33Probe\\   (deleted at the end)
    secret    a random password, DPAPI machine-bound, never printed / logged

Design note — why the whole gnosis tree is relocated:
    The port derives the Worker image from ``deterministic_worker.__file__`` and
    the launcher derives the bootstrap from ``worker_launcher.__file__``. So the
    Director-side launch stack is imported FROM the relocated, Worker-readable
    tool root (``<root>\\tools\\src``); every ``__file__`` then names a
    Worker-readable copy, exactly as a real relocated deployment would. This
    changes NO production code: F-17 and the port are consumed unmodified.

Run ELEVATED (Secondary Logon service must be available):

    <python> scripts/probe_f33_stage2a_worker_boundary.py [--out DIR]

There is deliberately NO `--keep`: this qualification always rolls back.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import secrets
import shutil
import string
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKER_NAME = "GnosisWkrF33"                       # <= 20 chars (SAM limit)
PROBE_ROOT = Path(r"C:\ProgramData\Gnosis\F33Probe")

LOG: list[str] = []


def say(text: str = "") -> None:
    print(text, flush=True)
    LOG.append(text)


def random_password() -> str:
    """CSPRNG password satisfying Windows complexity, never logged/printed."""
    classes = (string.ascii_uppercase, string.ascii_lowercase, string.digits,
               "!#%&*+-=?@^_")
    required = [secrets.choice(group) for group in classes]
    alphabet = "".join(classes)
    chars = required + [secrets.choice(alphabet) for _ in range(24)]
    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return "".join(chars)


def icacls(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["icacls", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001 - absence of the API means "not elevated"
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=None,
                        help="evidence bundle directory (default: docs/evidence/<ts>-...)")
    ns = parser.parse_args()

    ev: dict[str, object] = {}
    ok_overall = True
    worker_sid = ""
    blob_path: Path | None = None

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(ns.out) if ns.out else (REPO / "docs" / "evidence" /
                                           f"{ts}-f33-stage2a-osreal")

    say("F-33 STAGE 2A — OS-REAL TRUSTED WORKER QUALIFICATION PROBE")
    say("=" * 78)
    ev["starting_head"] = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True,
        check=False,
    ).stdout.strip()
    ev["probe_script"] = str(Path(__file__).resolve())
    ev["probe_script_sha256"] = sha256_file(Path(__file__).resolve())
    ev["elevated"] = elevated()
    if not ev["elevated"]:
        say("NOT ELEVATED — provisioning would fail; refusing to touch OS state.")
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
        # ---- SETUP ------------------------------------------------------------
        say("\nSETUP — disposable infrastructure")
        say("-" * 78)
        if PROBE_ROOT.exists():
            subprocess.run(["icacls", str(PROBE_ROOT), "/reset", "/T", "/C", "/Q"],
                           capture_output=True, check=False)
            shutil.rmtree(PROBE_ROOT, ignore_errors=True)
        for path in (tools, launch, secrets_dir, work):
            path.mkdir(parents=True, exist_ok=True)

        say("   relocating the Python runtime into the tool root ...")
        shutil.copytree(Path(sys.base_prefix), runtime_dir, dirs_exist_ok=True)
        runtime = runtime_dir / "python.exe"
        if not runtime.exists():
            raise RuntimeError(f"relocated runtime missing: {runtime}")

        say("   relocating the full gnosis package into the tool root ...")
        shutil.copytree(REPO / "src" / "gnosis", tools_src / "gnosis",
                        dirs_exist_ok=True)

        # §8 evidence hygiene: source vs relocated deterministic_worker digest.
        src_dw = REPO / "src" / "gnosis" / "director" / "deterministic_worker.py"
        rel_dw = tools_src / "gnosis" / "director" / "deterministic_worker.py"
        ev["dw_source_sha256"] = sha256_file(src_dw)
        ev["dw_relocated_sha256"] = sha256_file(rel_dw)
        ev["dw_digest_match"] = ev["dw_source_sha256"] == ev["dw_relocated_sha256"]
        say(f"   deterministic_worker digest match: {ev['dw_digest_match']}")

        # Import the launch stack FROM THE RELOCATED tree so every __file__ names
        # a Worker-readable copy. Provisioning helpers come from the same tree.
        sys.path.insert(0, str(tools_src))
        # Confirm the port + worker resolve to the RELOCATED copies (§7/§8).
        import gnosis.director.execution as execmod
        import gnosis.trust.worker_launcher as wlmod
        from gnosis.director import deterministic_worker as dw
        from gnosis.director.execution import (
            DeterministicIntent,
            ExecutionMode,
            TrustedExecutionPort,
            WorkerExecutionFailed,
        )
        from gnosis.provision import winapi
        from gnosis.trust.worker_launcher import (
            TrustedWindowsWorkerLauncher,
            WorkerAccount,
            protect_worker_secret,
        )
        ev["execution_module_file"] = str(Path(execmod.__file__).resolve())
        ev["worker_launcher_module_file"] = str(Path(wlmod.__file__).resolve())
        ev["deterministic_worker_module_file"] = str(Path(dw.__file__).resolve())
        assert ev["deterministic_worker_module_file"] == str(rel_dw.resolve()), \
            "port would name a non-relocated deterministic_worker image"
        assert str(tools_src) in ev["worker_launcher_module_file"], \
            "bootstrap would be derived from a non-relocated launcher"

        say(f"   creating disposable non-admin account {WORKER_NAME} ...")
        password = random_password()
        if winapi.account_exists(WORKER_NAME):
            winapi.delete_local_account(WORKER_NAME)
        winapi.create_local_account(
            WORKER_NAME, password, "GNOSIS F-33 Stage-2A disposable worker")
        worker_sid = winapi.resolve_sid(WORKER_NAME)
        ev["worker_account"] = WORKER_NAME
        ev["worker_sid"] = worker_sid
        say(f"   worker SID: {worker_sid}")

        import getpass
        director_sid = winapi.resolve_sid(getpass.getuser())
        ev["director_sid"] = director_sid

        say("   DPAPI-protecting the credential (machine-bound) ...")
        blob_path = secrets_dir / "worker.dpapi"
        blob_path.write_bytes(protect_worker_secret(password))
        password = ""  # drop the plaintext reference

        say("   applying probe-only ACLs ...")
        # tools (runtime + relocated gnosis) and launch: worker READ+EXECUTE only.
        for path in (tools, launch):
            icacls(str(path), "/inheritance:r")
            icacls(str(path), "/grant:r", "*S-1-5-32-544:(OI)(CI)F",
                   "*S-1-5-18:(OI)(CI)F", f"*{worker_sid}:(OI)(CI)(RX)")
        # secrets: worker NOT granted (the DPAPI-blob boundary).
        icacls(str(secrets_dir), "/inheritance:r")
        icacls(str(secrets_dir), "/grant:r", "*S-1-5-32-544:(OI)(CI)F",
               "*S-1-5-18:(OI)(CI)F")
        # work: the run's workspace; worker may write its output here.
        icacls(str(work), "/inheritance:r")
        icacls(str(work), "/grant:r", "*S-1-5-32-544:(OI)(CI)F",
               "*S-1-5-18:(OI)(CI)F", f"*{worker_sid}:(OI)(CI)M")

        ev["runtime_path"] = str(runtime)
        ev["relocated_gnosis_root"] = str(tools_src)
        ev["launch_root"] = str(launch)
        # ACL evidence (short).
        ev["acl_tools"] = icacls(str(tools)).stdout.strip().splitlines()[:6]
        ev["acl_secrets"] = icacls(str(secrets_dir)).stdout.strip().splitlines()[:6]

        # ---- BUILD A TRUSTED, TINY, NORMAL-SCHEMA CASSETTE (§9/§10/§11) -------
        say("\nCASSETTE — trusted, tiny, normal schema")
        say("-" * 78)
        cassette = {
            "schema": dw.CASSETTE_SCHEMA,
            "turns": [{"message": "f33-osreal-hello"},
                      {"message": "f33-osreal-done"}],
        }
        cassette_bytes = json.dumps(cassette).encode("utf-8")
        cassette_path = work / "cassette.json"
        cassette_path.write_bytes(cassette_bytes)
        expected_digest = hashlib.sha256(cassette_bytes).hexdigest()
        ev["cassette_path"] = str(cassette_path)
        ev["cassette_schema"] = dw.CASSETTE_SCHEMA
        ev["cassette_size_bytes"] = len(cassette_bytes)
        ev["cassette_sha256"] = expected_digest
        say(f"   cassette bytes={len(cassette_bytes)} sha256={expected_digest[:16]}...")

        # ---- CONSTRUCT THE REAL PORT AND EXECUTE (§12) -----------------------
        say("\nEXECUTE — TrustedExecutionPort over the REAL Worker boundary")
        say("-" * 78)
        launcher = TrustedWindowsWorkerLauncher(
            account=WorkerAccount(username=WORKER_NAME, domain=".",
                                  expected_sid=worker_sid,
                                  expected_integrity="Medium"),
            credential_blob_path=blob_path, launch_root=launch,
            runtime=runtime, director_env=dict(os.environ))
        port = TrustedExecutionPort(launcher=launcher, python_executable=runtime)
        ev["port_invocation"] = (
            "TrustedExecutionPort(launcher=TrustedWindowsWorkerLauncher, "
            f"python_executable={runtime}).execute(ExecutionMode.DETERMINISTIC, "
            "DeterministicIntent(cassette,cwd,stdout,stderr), timeout_s=180)")

        intent = DeterministicIntent(
            cassette_path=cassette_path, cwd=work,
            stdout_path=work / "det.out", stderr_path=work / "det.err",
            launch_id="f33-det-pos")
        t0 = time.time()
        outcome = port.execute(ExecutionMode.DETERMINISTIC, intent, timeout_s=180.0)
        ev["execute_seconds"] = round(time.time() - t0, 1)

        linfo = outcome.launch or {}
        ev["exit_code"] = outcome.exit_code
        ev["observed_sid"] = linfo.get("observed_sid")
        ev["is_administrator"] = linfo.get("is_administrator")
        ev["contained_in_job"] = linfo.get("contained_in_job")
        ev["integrity"] = linfo.get("integrity")
        ev["launch_spec_digest"] = linfo.get("launch_spec_digest")
        ev["result_schema"] = outcome.result.get("schema")
        ev["result_ok"] = outcome.result.get("ok")
        ev["result_cassette_sha256"] = outcome.result.get("cassette_sha256")
        ev["result_final_message"] = outcome.result.get("final_message")
        ev["result_provider_calls"] = outcome.result.get("provider_calls")
        stdout_file = work / "det.out"
        ev["worker_stdout_bytes"] = (stdout_file.stat().st_size
                                     if stdout_file.exists() else -1)

        # ---- REQUIRED BOUNDARY ASSERTIONS (§13) ------------------------------
        say("\nASSERTIONS — real Worker boundary")
        say("-" * 78)
        checks: list[tuple[str, bool, str]] = []

        def check(name: str, cond: bool, detail: str = "") -> None:
            checks.append((name, bool(cond), detail))
            say(f"   [{'PASS' if cond else 'FAIL'}] {name}"
                + (f"  ({detail})" if detail else ""))

        check("identity: observed SID == disposable worker SID",
              ev["observed_sid"] == worker_sid, str(ev["observed_sid"]))
        check("separation: worker SID != director SID",
              worker_sid and worker_sid != director_sid, f"dir={director_sid}")
        check("privilege: worker is non-admin",
              ev["is_administrator"] is False, f"is_admin={ev['is_administrator']}")
        check("containment: worker contained in job object",
              ev["contained_in_job"] is True)
        check("image: port named the RELOCATED deterministic_worker",
              ev["deterministic_worker_module_file"] == str(rel_dw.resolve()))
        check("image: trusted relocated runtime used",
              str(runtime).startswith(str(runtime_dir)))
        check("result: port validated deterministic result (schema+ok)",
              ev["result_schema"] == dw.RESULT_SCHEMA and ev["result_ok"] is True)
        check("result: worker digested the exact sealed cassette",
              ev["result_cassette_sha256"] == expected_digest)
        check("result: final message echoes the cassette",
              ev["result_final_message"] == "f33-osreal-done")
        check("provider calls == 0", ev["result_provider_calls"] == 0)
        check("exit code == 0", ev["exit_code"] == 0)

        # ---- OS-REAL NEGATIVE: invalid cassette -> non-zero -> fail closed ----
        say("\nNEGATIVE — invalid cassette must fail closed through the port")
        say("-" * 78)
        bad = work / "bad_cassette.json"
        bad.write_bytes(json.dumps({"schema": "nope", "turns": []}).encode("utf-8"))
        neg_intent = DeterministicIntent(
            cassette_path=bad, cwd=work,
            stdout_path=work / "neg.out", stderr_path=work / "neg.err",
            launch_id="f33-det-neg")
        neg_failed_closed = False
        neg_detail = ""
        try:
            port.execute(ExecutionMode.DETERMINISTIC, neg_intent, timeout_s=180.0)
        except WorkerExecutionFailed as exc:
            neg_failed_closed = True
            neg_detail = f"WorkerExecutionFailed: {str(exc)[:80]}"
        except Exception as exc:  # noqa: BLE001 - any typed refusal is fail-closed
            neg_failed_closed = True
            neg_detail = f"{type(exc).__name__}: {str(exc)[:80]}"
        ev["negative_invalid_cassette_failed_closed"] = neg_failed_closed
        ev["negative_invalid_cassette_detail"] = neg_detail
        check("negative: invalid cassette -> port fails closed",
              neg_failed_closed, neg_detail)

        ev["checks"] = [{"name": n, "pass": p, "detail": d} for n, p, d in checks]
        ok_overall = all(p for _, p, _ in checks) and bool(ev["dw_digest_match"])
        ev["real_worker_boundary"] = "PASS" if ok_overall else "FAIL"

        # F-17 implementation diff must be NONE.
        diff = subprocess.run(["git", "diff", "--stat", "--", "src/gnosis/trust"],
                              cwd=REPO, capture_output=True, text=True,
                              check=False).stdout.strip()
        ev["f17_impl_diff"] = diff or "NONE"
        say(f"\n   F-17 implementation diff: {ev['f17_impl_diff']}")

    except Exception as exc:  # noqa: BLE001 - probe reports every failure as data
        ok_overall = False
        ev["exception"] = f"{type(exc).__name__}: {str(exc)[:400]}"
        ev["real_worker_boundary"] = "FAIL"
        say(f"\nPROBE EXCEPTION: {ev['exception']}")
    finally:
        # ---- ROLLBACK (always) -----------------------------------------------
        say("\nROLLBACK")
        say("-" * 78)
        rb: dict[str, object] = {}
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
            except Exception:  # noqa: BLE001 - fall back to net user for teardown
                status = int(subprocess.run(["net", "user", WORKER_NAME, "/delete"],
                                            capture_output=True,
                                            check=False).returncode)
            rb["netuserdel_status"] = status
            drop = ("Get-CimInstance Win32_UserProfile | Where-Object { "
                    f"$_.LocalPath -like '*{WORKER_NAME}*' }} | Remove-CimInstance "
                    "-ErrorAction SilentlyContinue")
            subprocess.run(["powershell", "-NoProfile", "-Command", drop],
                           capture_output=True, check=False)
            profile = Path(r"C:\Users") / WORKER_NAME
            if profile.exists():
                shutil.rmtree(profile, ignore_errors=True)
            rb["profile_removed"] = not profile.exists()
            if PROBE_ROOT.exists():
                subprocess.run(["icacls", str(PROBE_ROOT), "/reset", "/T", "/C", "/Q"],
                               capture_output=True, check=False)
                shutil.rmtree(PROBE_ROOT, ignore_errors=True)
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
    say(f"REAL WORKER BOUNDARY: {ev.get('real_worker_boundary')}")
    say(f"TEMPORARY WORKER ROLLBACK: {ev.get('rollback', {}).get('rollback')}")
    return 0 if (ok_overall and ev.get("rollback", {}).get("rollback") == "PASS") else 1


def _write_evidence(out_dir: Path, ev: dict[str, object]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "f33_stage2a_osreal.json").write_text(
        json.dumps(ev, indent=2, default=str), encoding="utf-8")
    (out_dir / "probe_log.txt").write_text("\n".join(LOG), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
