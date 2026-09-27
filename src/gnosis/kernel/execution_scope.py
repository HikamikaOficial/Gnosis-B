"""A borrowed whole-brief grant: checks and cancellation, never resolution.

The outer supervisor owns acquisition/renewal/resolution. Inner phases may use
the scope but cannot resolve the claim after merely completing implementation.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from gnosis.kernel.claims import StaleClaimError, WorkAuthority, WorkGrant
from gnosis.kernel.lease import StaleLeaseError
from gnosis.runner.claude_cli_runner import CancellationToken


class ExecutionCancelled(RuntimeError):
    """The enclosing operation was cancelled before this phase could proceed."""


@dataclass(frozen=True)
class ExecutionScope:
    assert_current: Callable[[], None]
    cancellation: CancellationToken
    epoch: int
    holder: str
    commit_current: Callable[[Callable[[], None]], None] | None = None

    @classmethod
    def borrowed(cls, authority: WorkAuthority, grant: WorkGrant,
                 cancellation: CancellationToken) -> ExecutionScope:
        return cls(lambda: authority.assert_current(grant), cancellation,
                   grant.claim.epoch, grant.holder,
                   lambda action: authority.commit(grant, action))

    def commit(self, action: Callable[[], None]) -> None:
        def write() -> None:
            if self.cancellation.is_cancelled():
                raise ExecutionCancelled("enclosing execution was cancelled")
            action()
        try:
            if self.commit_current is None:
                self.check()
                write()
            else:
                self.commit_current(write)
        except (StaleClaimError, StaleLeaseError):
            self.cancellation.cancel()
            raise

    def check(self) -> None:
        try:
            self.assert_current()
        except (StaleClaimError, StaleLeaseError):
            self.cancellation.cancel()
            raise
        if self.cancellation.is_cancelled():
            raise ExecutionCancelled("enclosing execution was cancelled")
