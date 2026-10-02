"""Prove the F-17 Stage-8 provisioning suite catches what it claims.

Each mutant reintroduces a real provisioning defect: the worker granted write on
a trusted root, an inheritance strip removed, the credential blob left unwritten,
the service left unrestricted, ACLs applied after the deployment is observed, the
installer made non-idempotent, python._pth re-enabling site, and so on. A
SURVIVOR is a security property the unit suite does not actually check.

    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/mutation_check_stage8.py [--out PATH]

It edits `src/gnosis/provision/*` in place and restores it; do NOT run it
concurrently with the OS-real probe, which copies from `src/`.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
B = chr(92)  # a single backslash, spelled unambiguously

LAYOUT = "src/gnosis/provision/layout.py"
PROV = "src/gnosis/provision/provisioner.py"

SUITE = [
    "tests/test_provision_layout.py",
    "tests/test_provisioner.py",
]


@dataclass(frozen=True)
class Mutant:
    name: str
    description: str
    edits: list[tuple[str, str, str]] = field(default_factory=list)


# -- layout / ACL-matrix anchors --------------------------------------------
_SECRETS = ('             "the DPAPI worker-credential blob; the worker is '
            'DENIED (no ACE)",\n             True, ((_M, _F), (_S, _F))),')
_SECRETS_WORKER = ('             "the DPAPI worker-credential blob; the worker is '
                   'DENIED (no ACE)",\n             True, ((_M, _F), (_S, _F), '
                   '(_W, _MOD))),')
_SECRETS_NOINHERIT = ('             "the DPAPI worker-credential blob; the worker '
                      'is DENIED (no ACE)",\n             False, ((_M, _F), '
                      '(_S, _F))),')
_BUNDLES = ('             "trusted capture, read by the service, WORKER HAS NO '
            'ACE",\n             True, ((_M, _F), (_S, _F), (_SVC, _R))),')
_BUNDLES_WORKER = ('             "trusted capture, read by the service, WORKER HAS '
                   'NO ACE",\n             True, ((_M, _F), (_S, _F), (_SVC, _R), '
                   '(_W, _MOD))),')
_ANCHORS = ('             "the AnchorStore ledger + watermark; the service commits '
            'here",\n             True, ((_M, _F), (_S, _F), (_SVC, _MOD))),')
_ANCHORS_WORKER = ('             "the AnchorStore ledger + watermark; the service '
                   'commits here",\n             True, ((_M, _F), (_S, _F), '
                   '(_SVC, _MOD), (_W, _MOD))),')
_PUBLISHER = ('             "service reads+executes it, the worker has no access",'
              '\n             True, ((_M, _F), (_S, _F), (_SVC, _RX))),')
_PUBLISHER_WORKER = ('             "service reads+executes it, the worker has no '
                     'access",\n             True, ((_M, _F), (_S, _F), (_SVC, '
                     '_RX), (_W, _F))),')
_RUNTIME = ('             "the deployed Python interpreter tree (with '
            'python._pth)",\n             True, ((_M, _F), (_S, _F), (_SVC, _RX), '
            '(_W, _RX))),')
_RUNTIME_WORKER_MOD = ('             "the deployed Python interpreter tree (with '
                       'python._pth)",\n             True, ((_M, _F), (_S, _F), '
                       '(_SVC, _RX), (_W, _MOD))),')

_RELEASE_BASE = 'return f"{self.code_base}' + B + B + 'releases' + B + B + '{self.release_id}"'
_RELEASE_BASE_FLAT = 'return f"{self.code_base}"'
_BUNDLES_PATH = ('    def bundles_root(self) -> str:\n        return '
                 'f"{self.state_base}' + B + B + 'bundles"')
_BUNDLES_PATH_WORK = ('    def bundles_root(self) -> str:\n        return '
                      'self.work_base')

# -- provisioner anchors ----------------------------------------------------
_LIB = '        "Lib' + B + 'n"'
_LIB_SITE = '        "Lib' + B + 'n"\n        "import site' + B + 'n"'
_LIB_SITEPKG = '        "Lib' + B + 'n"\n        "site-packages' + B + 'n"'
_IMAGEPATH = ("return f'" + '"{runtime_executable}" -I -B "{service_entry}" '
              '"{config_path}"' + "'")
_IMAGEPATH_NOISO = ("return f'" + '"{runtime_executable}" -B "{service_entry}" '
                    '"{config_path}"' + "'")
_GRANT_R = '        grant = ["icacls", path, "/grant:r"]'
_GRANT_ADD = '        grant = ["icacls", path, "/grant"]'
_INHERIT_IF = '    if spec.break_inheritance:'
_INHERIT_NEVER = '    if False:  # MUTANT: never strip inheritance'
_CFG_WORKER = '        "authorized_worker_sid": sids.worker,'
_CFG_WORKER_WRONG = '        "authorized_worker_sid": sids.service,'
_CFG_STATE = '        "trust_state_root": lay.state_base,'
_CFG_STATE_CODE = '        "trust_state_root": lay.code_release_base,'
_ACL_THEN_OBSERVE = (
    '        self._apply_acls(sids)              # ACLs BEFORE observation '
    '(digest binds them)\n        digest, observed = self._observe(sids)')
_OBSERVE_THEN_ACL = (
    '        digest, observed = self._observe(sids)\n        self._apply_acls('
    'sids)              # ACLs BEFORE observation (digest binds them)')
_SIDTYPE = ('        self._checked(["sc.exe", "sidtype", name, "restricted"], '
            '"sc sidtype")')
_SIDTYPE_GONE = '        pass  # MUTANT: no sidtype restricted'
_BLOB = '        self.ops.write_bytes(self.config.layout.secrets_blob, blob)'
_BLOB_GONE = '        pass  # MUTANT: credential blob not written'
_UNINSTALL = (
    '        self.ops.run(["sc.exe", "stop", name])\n'
    '        self.ops.run(["sc.exe", "delete", name])\n'
    '        if remove_worker:\n'
    '            self.ops.delete_worker(self.config.worker_username)')
_UNINSTALL_REORDER = (
    '        if remove_worker:\n'
    '            self.ops.delete_worker(self.config.worker_username)\n'
    '        self.ops.run(["sc.exe", "stop", name])\n'
    '        self.ops.run(["sc.exe", "delete", name])')
_ACCT_GUARD = '        if self.ops.account_exists(self.config.worker_username):'
_ACCT_ALWAYS = '        if False:  # MUTANT: always create the worker account'
_SVC_GUARD = ('        exists_rc, _ = self.ops.run(["sc.exe", "query", name])\n'
              '        if exists_rc == 0:')
_SVC_ALWAYS = ('        exists_rc, _ = self.ops.run(["sc.exe", "query", name])\n'
               '        if False:  # MUTANT: always sc create')


MUTANTS: list[Mutant] = [
    Mutant("S8M01", "worker granted MODIFY on the credential blob root",
           [(LAYOUT, _SECRETS, _SECRETS_WORKER)]),
    Mutant("S8M02", "worker granted MODIFY on the authoritative bundles (Stage 7 R5)",
           [(LAYOUT, _BUNDLES, _BUNDLES_WORKER)]),
    Mutant("S8M03", "worker granted MODIFY on the anchor ledger",
           [(LAYOUT, _ANCHORS, _ANCHORS_WORKER)]),
    Mutant("S8M04", "worker granted FULL on the publisher code",
           [(LAYOUT, _PUBLISHER, _PUBLISHER_WORKER)]),
    Mutant("S8M05", "worker upgraded from RX to MODIFY on the runtime",
           [(LAYOUT, _RUNTIME, _RUNTIME_WORKER_MOD)]),
    Mutant("S8M06", "the credential blob root stops stripping inheritance",
           [(LAYOUT, _SECRETS, _SECRETS_NOINHERIT)]),
    Mutant("S8M07", "code releases are no longer versioned (rollback impossible)",
           [(LAYOUT, _RELEASE_BASE, _RELEASE_BASE_FLAT)]),
    Mutant("S8M08", "the authoritative bundles collapse onto the worker work root",
           [(LAYOUT, _BUNDLES_PATH, _BUNDLES_PATH_WORK)]),
    Mutant("S8M09", "python._pth re-enables site (import site)",
           [(PROV, _LIB, _LIB_SITE)]),
    Mutant("S8M10", "python._pth puts site-packages on the path",
           [(PROV, _LIB, _LIB_SITEPKG)]),
    Mutant("S8M11", "the service ImagePath drops -I isolation",
           [(PROV, _IMAGEPATH, _IMAGEPATH_NOISO)]),
    Mutant("S8M12", "icacls grants are additive (/grant) not replacing (/grant:r)",
           [(PROV, _GRANT_R, _GRANT_ADD)]),
    Mutant("S8M13", "the inheritance strip is skipped for every root",
           [(PROV, _INHERIT_IF, _INHERIT_NEVER)]),
    Mutant("S8M14", "config.json binds the service SID as the authorized worker",
           [(PROV, _CFG_WORKER, _CFG_WORKER_WRONG)]),
    Mutant("S8M15", "config.json points trust_state_root at the versioned code base",
           [(PROV, _CFG_STATE, _CFG_STATE_CODE)]),
    Mutant("S8M16", "ACLs are applied AFTER the deployment is observed",
           [(PROV, _ACL_THEN_OBSERVE, _OBSERVE_THEN_ACL)]),
    Mutant("S8M17", "the service is left UNRESTRICTED (no sidtype restricted)",
           [(PROV, _SIDTYPE, _SIDTYPE_GONE)]),
    Mutant("S8M18", "the DPAPI credential blob is never written",
           [(PROV, _BLOB, _BLOB_GONE)]),
    Mutant("S8M19", "uninstall removes the worker BEFORE stopping the service",
           [(PROV, _UNINSTALL, _UNINSTALL_REORDER)]),
    Mutant("S8M20", "install always creates the worker (not idempotent)",
           [(PROV, _ACCT_GUARD, _ACCT_ALWAYS)]),
    Mutant("S8M21", "install always sc-creates the service (not idempotent)",
           [(PROV, _SVC_GUARD, _SVC_ALWAYS)]),
]


def _pytest() -> tuple[int, str]:
    proc = subprocess.run([sys.executable, "-m", "pytest", *SUITE, "-q",
                           "-p", "no:cacheprovider"],
                          cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)
    tail = (proc.stdout.strip().splitlines() or [""])[-1][:200]
    return proc.returncode, tail


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    lines: list[str] = []

    def say(message: str) -> None:
        print(message)
        lines.append(message)

    touched = sorted({rel for m in MUTANTS for rel, _, _ in m.edits})
    originals = {rel: (REPO / rel).read_text(encoding="utf-8") for rel in touched}

    say("F-17 STAGE 8 — MUTATION CHECK OVER THE LAYOUT, ACL MATRIX AND PROVISIONER")
    say("=" * 74)
    code, tail = _pytest()
    say(f"BASELINE: exit={code}  {tail}")
    if code != 0:
        say("baseline is not green; refusing to attribute mutant verdicts")
        return 1
    say("")

    survived: list[str] = []
    try:
        for mutant in MUTANTS:
            applied = True
            for rel, old, new in mutant.edits:
                src = (REPO / rel).read_text(encoding="utf-8")
                if old not in src:
                    applied = False
                    break
                (REPO / rel).write_text(src.replace(old, new, 1),
                                        encoding="utf-8", newline="")
            if not applied:
                survived.append(f"{mutant.name} (NOT APPLIED)")
                say(f"{mutant.name}: {mutant.description}\n  verdict: NOT APPLIED")
            else:
                code, tail = _pytest()
                say(f"{mutant.name}: {mutant.description}")
                say(f"  result: exit={code}  {tail}")
                say(f"  verdict: {'CAUGHT' if code != 0 else 'SURVIVED'}")
                if code == 0:
                    survived.append(mutant.name)
            for rel, text in originals.items():
                (REPO / rel).write_text(text, encoding="utf-8", newline="")
            say("")
    finally:
        for rel, text in originals.items():
            (REPO / rel).write_text(text, encoding="utf-8", newline="")

    code, tail = _pytest()
    say(f"RESTORED: exit={code}  {tail}")
    say(f"mutants: {len(MUTANTS)}  survived/aborted: {len(survived)}"
        + (f"  -> {survived}" if survived else ""))
    if args.out:
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if survived or code != 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
