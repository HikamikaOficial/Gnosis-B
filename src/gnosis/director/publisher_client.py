"""Director-side client for the F-17 Publisher service (F-33 Stage 2C-A).

The canonical production publication path talks to the ALREADY-QUALIFIED F-17
Publisher over its named pipe; it does not reimplement the anchor, the watermark,
the grammar, or the service. This module is a NARROW consumer: it can send
exactly one bounded ``PUBLISH <run_id>`` request to the trusted, deployment-owned
endpoint and validate the bounded response. It exposes no arbitrary pipe command
and accepts no operator-supplied endpoint.

`src/gnosis/trust/* is not touched by this module.`

Two clients share one interface:
- `PipePublisherClient` — production: connects to the real local named pipe.
- `InProcessPublisherClient` — TEST / component qualification only (ADR-0032 §16
  allows in-process `durable_publish` off the production operator route); it drives
  the real trust protocol in-process so the seam can be qualified without a running
  Windows service. It must NEVER be selected by the operator route.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# Mirror of the F-17 wire contract (trust/publisher.py) — consumed, not owned.
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MAX_REQUEST_BYTES = 512      # F-17 MAX_REQUEST_BYTES
MAX_RESPONSE_BYTES = 256     # a bounded reply; anything larger fails closed


class PublisherClientError(Exception):
    """The publication request could not be completed (fail closed)."""


@dataclass(frozen=True)
class PublishResponse:
    """A bounded, validated Publisher reply. `anchored` is True only for an
    ANCHORED / ALREADY_ANCHORED reply — but it is NEVER the authority for
    operator success: the caller re-reads the persisted publication state."""

    raw: str
    anchored: bool


def build_publish_request(run_id: str) -> str:
    """The one bounded request. A run_id that is not the F-17 grammar (and so
    could express a path or an extra verb) is refused before anything is sent."""
    if not _RUN_ID.match(run_id):
        raise PublisherClientError(f"run_id {run_id!r} is not a valid publish selector")
    request = f"PUBLISH {run_id}"
    if len(request.encode("utf-8")) > MAX_REQUEST_BYTES:
        raise PublisherClientError("publish request exceeds the bound")
    return request


def parse_publish_response(raw: str) -> PublishResponse:
    """Validate the bounded reply against the exact F-17 grammar; fail closed on
    anything malformed, oversized, refused or unexpected."""
    if len(raw.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise PublisherClientError("publisher response exceeds the bound (fail closed)")
    text = raw.strip()
    if text.startswith("REJECTED:"):
        raise PublisherClientError(f"publisher refused: {text}")
    if re.match(r"^ANCHORED:[0-9a-f]{12}:seq=\d+$", text) or \
            re.match(r"^ALREADY_ANCHORED:seq=\d+$", text):
        return PublishResponse(raw=text, anchored=True)
    raise PublisherClientError(f"unexpected publisher response {text!r} (fail closed)")


class PublisherClient(Protocol):
    def publish(self, run_id: str) -> PublishResponse: ...


class PipePublisherClient:
    """Production client: one bounded PUBLISH over the trusted local named pipe.

    The endpoint is trusted deployment/service configuration, never operator work
    input. Command/response are bounded; connect/op are time-bounded; any failure
    fails closed. The live CreateFileW round-trip is exercised OS-real in Stage
    2C-B — this class contains no fallback and no arbitrary-command surface."""

    def __init__(self, pipe_name: str, *, connect_timeout_ms: int = 5000,
                 op_timeout_ms: int = 30000) -> None:
        if not pipe_name.startswith(r"\\.\pipe\\") and not pipe_name.startswith(r"\\.\pipe"):
            raise PublisherClientError(
                f"publisher endpoint {pipe_name!r} is not a local pipe path")
        self._pipe_name = pipe_name
        self._connect_timeout_ms = connect_timeout_ms
        self._op_timeout_ms = op_timeout_ms

    @property
    def endpoint(self) -> str:
        return self._pipe_name

    def publish(self, run_id: str) -> PublishResponse:
        request = build_publish_request(run_id)
        raw = self._round_trip(request)
        return parse_publish_response(raw)

    def _round_trip(self, request: str) -> str:  # pragma: no cover - OS-real (2C-B)
        import ctypes
        from ctypes import wintypes as w

        k32 = ctypes.windll.kernel32
        generic_rw = 0x80000000 | 0x40000000
        open_existing = 3
        invalid = ctypes.c_void_p(-1).value
        # Bounded wait for the single-instance server to be free.
        if not k32.WaitNamedPipeW(self._pipe_name, self._connect_timeout_ms):
            raise PublisherClientError(
                f"publisher service unavailable at {self._pipe_name} (fail closed)")
        handle = k32.CreateFileW(self._pipe_name, generic_rw, 0, None,
                                 open_existing, 0, None)
        if handle in (invalid, None, 0):
            raise PublisherClientError(
                f"could not open publisher pipe (winerr {ctypes.get_last_error()})")
        try:
            raw = request.encode("utf-8")
            written = w.DWORD(0)
            if not k32.WriteFile(handle, raw, len(raw), ctypes.byref(written), None):
                raise PublisherClientError("publisher write failed (fail closed)")
            buf = ctypes.create_string_buffer(MAX_RESPONSE_BYTES + 1)
            read = w.DWORD(0)
            if not k32.ReadFile(handle, buf, MAX_RESPONSE_BYTES + 1,
                                ctypes.byref(read), None):
                raise PublisherClientError("publisher read failed (fail closed)")
            return buf.raw[:read.value].decode("utf-8", "replace")
        finally:
            k32.CloseHandle(handle)


class InProcessPublisherClient:
    """TEST / component-qualification client (NON-PRODUCTION, ADR-0032 §16).

    Drives the REAL trust protocol (`durable_publish`) in-process so the seam can
    be qualified without a running service. The canonical operator route must
    never construct this (enforced by a structural guard)."""

    def __init__(self, trust_state_root: Path, expected_deployment_digest: str,
                 authorized_worker_sid: str) -> None:
        self._trust_state_root = trust_state_root
        self._expected_deployment_digest = expected_deployment_digest
        self._authorized_worker_sid = authorized_worker_sid

    def publish(self, run_id: str) -> PublishResponse:
        from gnosis.trust.anchor import AnchorStore
        from gnosis.trust.publication import durable_publish
        from gnosis.trust.publisher import Publisher, PublisherConfig
        from gnosis.trust.run_identity import TrustedRunIdentityStore

        build_publish_request(run_id)  # same bounded-selector validation
        config = PublisherConfig(
            trust_state_root=self._trust_state_root,
            evidence_root=self._trust_state_root / "evidence",
            authorized_worker_sid=self._authorized_worker_sid,
            expected_deployment_digest=self._expected_deployment_digest)
        run_store = TrustedRunIdentityStore(config.runidentity_root)
        anchor_store = AnchorStore(config.anchors_root, require_high=False)
        identity = run_store.read(run_id).identity
        request = Publisher(config).publication_request(run_id, identity)
        durable_publish(anchor_store, run_store, request,
                        Path(identity.bundle_path))
        return PublishResponse(raw="ANCHORED:inprocess", anchored=True)
