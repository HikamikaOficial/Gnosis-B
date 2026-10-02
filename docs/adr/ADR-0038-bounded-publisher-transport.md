# ADR-0038 — bound the Director's Windows pipe transport

Status: implemented and component-tested with real Windows pipes; dedicated
Worker/service deployment qualification remains required.

## Problem

PipePublisherClient stored op_timeout_ms without using it. Synchronous WriteFile
and ReadFile could wait forever. The ctypes client also lacked explicit 64-bit
handle signatures and requested GENERIC_WRITE, which includes rights deliberately
absent from the existing server's worker ACL.

## Decision

The Director launches a small stdlib-only transport helper using its own Python
interpreter/account, with -I -B and an absolute package-file path. No shell,
provider, credentials or alternate authority are introduced. The helper implements
the existing bounded request/response framing with explicit ctypes signatures and
the server's existing WORKER_PIPE_ACCESS mask (0x00120083). Trust-plane code and
protocol are unchanged.

subprocess.run enforces a total deadline of connect_timeout_ms + op_timeout_ms,
including helper startup. On timeout it kills and reaps the helper, closing its
native handles without abandoning an I/O thread or freeing a live native buffer.
Timeout values are integer milliseconds within 1..300000. The helper emits at
most MAX_RESPONSE_BYTES + 1; oversized or malformed replies fail closed.

A timeout means publication outcome UNKNOWN. Terminating the client does not
cancel a request already accepted by the service. Recovery must reconcile the
same run ID through the existing Publisher and inspect persisted authoritative
state. A response alone never establishes ANCHORED.

## Evidence

tests/test_publisher_transport_windows.py uses real Windows named pipes for a
valid reply, an unresponsive server and an oversized message. It verifies the
exact PUBLISH request and that the child process is terminal after timeout.
Combined client/transport/publication/pipe regression: 36 passed, 9 subtests.
This proves bounded communication, not deployed service/Worker qualification or
the outstanding publication authorization concurrency invariant.
