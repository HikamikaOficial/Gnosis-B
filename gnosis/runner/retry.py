"""Retry policy with a hard cap, enforces the constitution's "no infinite
retry loops" rule at the type level: max_attempts is required and finite."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Generic, Optional, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    backoff_base_s: float = 2.0
    backoff_factor: float = 2.0
    max_backoff_s: float = 60.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("RetryPolicy.max_attempts must be >= 1")

    def backoff_for(self, attempt: int) -> float:
        delay = self.backoff_base_s * (self.backoff_factor ** max(attempt - 1, 0))
        return min(delay, self.max_backoff_s)


@dataclass(frozen=True)
class AttemptRecord(Generic[T]):
    attempt: int
    result: T
    is_final: bool


def execute_with_retry(
    attempt_fn: Callable[[int], T],
    should_retry: Callable[[T], bool],
    policy: RetryPolicy,
    on_attempt: Optional[Callable[["AttemptRecord[T]"], None]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> list:
    """Call attempt_fn(attempt_number) up to policy.max_attempts times.

    Stops as soon as should_retry(result) is False (success), or once the
    hard attempt cap is reached (failure, never retried indefinitely).
    """
    records: list = []
    for attempt in range(1, policy.max_attempts + 1):
        result = attempt_fn(attempt)
        needs_retry = should_retry(result)
        is_final = (not needs_retry) or (attempt == policy.max_attempts)
        record = AttemptRecord(attempt=attempt, result=result, is_final=is_final)
        records.append(record)
        if on_attempt:
            on_attempt(record)
        if is_final:
            break
        sleep_fn(policy.backoff_for(attempt))
    return records
