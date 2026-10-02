"""The publisher service: compose the trusted pieces, start nothing else.

THE ORDER IS THE DESIGN.

    1. read the provisioned configuration      (never from a client)
    2. RECONCILE durable publication state     (before accepting any request)
    3. create the pipe as its FIRST instance   (fail closed if squatted)
    4. serve one bounded request at a time

Recovery happens BEFORE the pipe exists. A publisher that accepted requests
while its own committed state was unreconciled could answer `ALREADY_ANCHORED`
for a record that was never committed, or re-append one that was - so the
question "what is actually committed" is settled while nobody can ask anything.

WHERE THE CONFIGURATION COMES FROM. A JSON file named on the service's command
line, which is the service's `ImagePath` - set by an administrator at install
time and, as the Stage 6 probe demonstrates, not writable by the Worker.
Everything authority-bearing in it (the authorized worker SID, the expected
deployment digest, the roots) therefore arrives from provisioning and never
from the wire.
"""
from __future__ import annotations

import json
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from gnosis.trust.anchor import AnchorStore
from gnosis.trust.launch import AuthorityUnavailable
from gnosis.trust.pipe_server import PipeServer, worker_pipe_sddl
from gnosis.trust.publication import (
    LedgerNotUnderDurableProtocol,
    initialise_durable_store,
    reconcile_publication_state,
)
from gnosis.trust.publisher import Publisher, PublisherConfig
from gnosis.trust.run_identity import TrustedRunIdentityStore
from gnosis.trust.service_host import ServiceHost

SERVICE_CONFIG_SCHEMA = "gnosis.trust.publisher_service.v1"

_REQUIRED = (
    "schema", "service_name", "pipe_name", "service_sid",
    "trust_state_root", "evidence_root", "authorized_worker_sid",
    "expected_deployment_digest", "log_path",
)


@dataclass(frozen=True)
class ServiceConfig:
    service_name: str
    pipe_name: str
    service_sid: str
    trust_state_root: Path
    evidence_root: Path
    authorized_worker_sid: str
    expected_deployment_digest: str
    log_path: Path

    @classmethod
    def load(cls, path: Path) -> ServiceConfig:
        """Read the provisioned configuration, or refuse to start.

        Every field is required and none has a default. A publisher that
        started with a missing `authorized_worker_sid` and a permissive
        fallback would be a publisher that authorizes everyone, so an absent
        field is a startup failure rather than a silent value.
        """
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AuthorityUnavailable(
                f"publisher service configuration {path} is unreadable: {exc}") from exc
        if not isinstance(raw, dict) or raw.get("schema") != SERVICE_CONFIG_SCHEMA:
            raise AuthorityUnavailable(
                f"publisher service configuration {path} is not {SERVICE_CONFIG_SCHEMA}")
        missing = [name for name in _REQUIRED
                   if not isinstance(raw.get(name), str) or not raw.get(name)]
        if missing:
            raise AuthorityUnavailable(
                f"publisher service configuration {path} is missing: "
                f"{', '.join(missing)}; fail closed")
        return cls(
            service_name=raw["service_name"],
            pipe_name=raw["pipe_name"],
            service_sid=raw["service_sid"],
            trust_state_root=Path(raw["trust_state_root"]),
            evidence_root=Path(raw["evidence_root"]),
            authorized_worker_sid=raw["authorized_worker_sid"],
            expected_deployment_digest=raw["expected_deployment_digest"],
            log_path=Path(raw["log_path"]),
        )

    def publisher_config(self) -> PublisherConfig:
        return PublisherConfig(
            trust_state_root=self.trust_state_root,
            evidence_root=self.evidence_root,
            authorized_worker_sid=self.authorized_worker_sid,
            expected_deployment_digest=self.expected_deployment_digest)


def _logger(path: Path) -> Callable[[str], None]:
    def log(message: str) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(message + "\n")
        except OSError:
            # A service that dies because it could not write its own log is a
            # service an attacker stops by filling a disk.
            pass
    return log


def recover_at_startup(config: ServiceConfig,
                       log: Callable[[str], None]) -> None:
    """Settle what is committed before anything may ask.

    A store with no watermark is either brand new - safe to initialise, since an
    empty ledger commits nothing - or a ledger this protocol did not write, which
    is refused. Either way the decision is made here, once, with no client
    connected.
    """
    publisher_config = config.publisher_config()
    store = AnchorStore(publisher_config.anchors_root, require_high=False)
    run_store = TrustedRunIdentityStore(publisher_config.runidentity_root)
    try:
        report = reconcile_publication_state(
            store, run_store,
            expected_deployment_digest=config.expected_deployment_digest,
            repair_uncommitted_tail=True)
    except LedgerNotUnderDurableProtocol:
        watermark = initialise_durable_store(store)
        log(f"durable store initialised at committed_seq={watermark.committed_seq}")
        return
    log(f"recovery: committed_seq={report.committed_seq} "
        f"reconciled={len(report.reconciled_run_ids)} "
        f"healthy={len(report.healthy_run_ids)} "
        f"foreign_deployment={len(report.foreign_deployment_run_ids)} "
        f"tail_records={report.uncommitted_tail_records} "
        f"tail_discarded={report.tail_discarded}")


def run_service(config_path: Path) -> int:
    """Start the service. Returns a process exit code."""
    config = ServiceConfig.load(config_path)
    log = _logger(config.log_path)
    log(f"starting {config.service_name} for worker {config.authorized_worker_sid}")

    recover_at_startup(config, log)

    publisher = Publisher(config.publisher_config(), log=log)
    server = PipeServer(
        config.pipe_name,
        worker_pipe_sddl(config.authorized_worker_sid, config.service_sid),
        publisher.handle, log=log)

    def on_start(stop_event: threading.Event) -> None:
        server.serve_forever()

    host = ServiceHost(config.service_name, on_start, server.stop, log)
    host.run()
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        return 2
    try:
        return run_service(Path(argv[1]))
    except AuthorityUnavailable as exc:
        sys.stderr.write(f"publisher service refused to start: {exc}\n")
        return 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
