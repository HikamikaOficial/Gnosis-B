"""Sortable, collision-resistant task/run identifiers.

Format: "<PREFIX>-<UTC timestamp>-<random hex>", e.g.
"TASK-20260819T023000123Z-9f3a2b1c". Lexicographic sort tracks chronological
order closely (millisecond resolution, ties broken by random suffix), which
keeps run directories and ledger listings naturally orderable without a
database.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

_TASK_PREFIX = "TASK"
_RUN_PREFIX = "RUN"


def _new_id(prefix: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")[:-3] + "Z"
    rand = os.urandom(4).hex()
    return f"{prefix}-{ts}-{rand}"


def new_task_id() -> str:
    return _new_id(_TASK_PREFIX)


def new_run_id() -> str:
    return _new_id(_RUN_PREFIX)


def is_task_id(value: str) -> bool:
    return value.startswith(f"{_TASK_PREFIX}-")


def is_run_id(value: str) -> bool:
    return value.startswith(f"{_RUN_PREFIX}-")
