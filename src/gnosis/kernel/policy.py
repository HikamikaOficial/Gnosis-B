"""Fail-closed, stateless policy verdicts (Directive 8).

From docs/research/REFERENCE_REPOSITORY_FINDINGS.md §8. Four properties,
each of which exists because its absence is a known failure mode:

**Pure and stateless.** Adapters build a complete `ActionSnapshot` per
intervention point; `PolicyEngine.decide` returns exactly one
`PolicyDecision`. The engine holds no state, reads no clock and touches
no filesystem, so the same snapshot always yields the same verdict — and
a verdict can be recomputed later from recorded evidence.

**Every internal failure is a deny, in a reserved namespace.** A rule
that raises, returns garbage, or emits a reserved reason collapses to
DENY with a `runtime_error:*` reason that rules themselves may not
produce (validated, not merely documented). A deny-by-error is therefore
always distinguishable from a deliberate policy deny — the two demand
very different human responses.

**Configuration gaps are never consent.** An unconfigured intervention
point denies. An undeclared tool denies. Silence is not permission.

**Approvals bind to the action identity.** An escalation is approved for
the sha256 of exactly what was evaluated; change one flag or one path and
the approval no longer applies (anti-TOCTOU). Approval state lives in
`ApprovalStore`, deliberately outside the pure engine.

Decisions key on **structured, parsed intent** (`CommandIntent`: program,
flags, operands, resolved paths), never on substring matching against a
raw command line — the classic bypass surface.

`EnforcementMatrix` records, per adapter and restriction, whether the
restriction is mechanically enforced, sandbox-approximated, prompt-only,
or ignored. The kernel's least-privilege decisions are only as honest as
this table, so it is machine-checked rather than prose.
"""
from __future__ import annotations

import re
import shlex
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any

from .canonical import hash_canonical

# Reason namespaces. Rules may use any prefix EXCEPT the reserved ones:
# reserving them is what keeps "the policy said no" distinguishable from
# "the policy engine broke".
RESERVED_REASON_PREFIXES = ("runtime_error:", "policy_gap:")


class PolicyError(RuntimeError):
    pass


class Verdict(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    WARN = "WARN"          # proceed, but the decision is recorded loudly
    ESCALATE = "ESCALATE"  # NEEDS_HUMAN: blocked pending bound approval
    TRANSFORM = "TRANSFORM"  # proceed with the engine-supplied replacement


# Deny is absolute; escalate outranks warn; warn outranks allow. A single
# rule can therefore never be overridden into something weaker by another
# rule's opinion.
_PRECEDENCE = {
    Verdict.DENY: 5,
    Verdict.ESCALATE: 4,
    Verdict.TRANSFORM: 3,
    Verdict.WARN: 2,
    Verdict.ALLOW: 1,
}


@dataclass(frozen=True)
class CommandIntent:
    """Parsed command intent — what a rule reasons about.

    Rules must never pattern-match a raw command string: quoting,
    equivalent flag spellings and path aliasing make substring checks a
    bypass surface, not a control.

    ``cwd`` is part of the intent, not ambient context: ``rm -rf build``
    means something very different in a scratch worktree than in a
    production checkout, and an approval that could not tell them apart
    would be worthless (verified: without this, both produced the same
    action_id).
    """

    program: str
    flags: tuple[str, ...] = ()
    operands: tuple[str, ...] = ()
    resolved_paths: tuple[str, ...] = ()
    cwd: str | None = None
    # Values attached to flags (`--output=/etc/x`), separated so a rule
    # sees them instead of them hiding inside an opaque flag token.
    flag_values: tuple[tuple[str, str], ...] = ()
    # Tokens the SHELL will expand (`~/...`, `$HOME/...`, `%VAR%\...`).
    # The kernel cannot resolve them purely and refuses to guess, so they
    # are surfaced rather than laundered into a false in-workspace path.
    unexpanded: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "program": self.program, "flags": list(self.flags),
            "operands": list(self.operands),
            "resolved_paths": list(self.resolved_paths),
            "cwd": self.cwd,
            "flag_values": [list(pair) for pair in self.flag_values],
            "unexpanded": list(self.unexpanded),
        }

    def has_flag(self, *names: str) -> bool:
        """True when any of ``names`` is present, in either spelling
        (`--output x` or `--output=x`)."""
        bare = {flag.split("=", 1)[0] for flag in self.flags}
        return any(name in bare for name in names)

    def value_for(self, *names: str) -> str | None:
        for flag, value in self.flag_values:
            if flag in names:
                return value
        return None


def parse_command(argv: Sequence[str] | str, cwd: Path | None = None) -> CommandIntent:
    """Parse an argv (or a shell string) into structured intent.

    Paths are resolved against ``cwd`` when given, so a rule reasons about
    where a write actually lands rather than about the literal token — the
    ``../../etc`` class of bypass.

    Resolution is deliberately **over-inclusive**: with a ``cwd`` every
    operand and every attached flag value is interpreted as a candidate
    path. A non-path operand then resolves to something harmlessly inside
    the workspace, while a path that the old "does it contain a slash?"
    heuristic missed no longer slips past a workspace rule unseen. For a
    fail-closed engine, over-resolving is the safe direction.
    """
    tokens = _tokenize(argv) if isinstance(argv, str) else list(argv)
    if not tokens:
        raise PolicyError("cannot parse an empty command")
    program = tokens[0]
    flags: list[str] = []
    operands: list[str] = []
    flag_values: list[tuple[str, str]] = []
    for token in tokens[1:]:
        if token.startswith("-") and token != "-" and token != "--":
            flags.append(token)
            name, value = _split_attached_value(token)
            if value:
                flag_values.append((name, value))
        else:
            operands.append(token)

    candidates = [*operands, *(value for _, value in flag_values)]
    resolved: list[str] = []
    unexpanded: list[str] = []
    for candidate_text in candidates:
        if _needs_shell_expansion(candidate_text):
            # `~/.ssh/id_rsa`, `$HOME/x`, `%USERPROFILE%\x`: the shell will
            # turn these into absolute paths the kernel cannot compute
            # purely. Anchoring them under cwd would MANUFACTURE a false
            # in-workspace path — the exact laundering a workspace rule
            # must not be handed (adversarial review). They are surfaced
            # separately so a rule can deny on their mere presence.
            if candidate_text not in unexpanded:
                unexpanded.append(candidate_text)
            continue
        if cwd is None and not _looks_like_path(candidate_text):
            continue  # no anchor to resolve against; do not invent one
        candidate = Path(candidate_text)
        if cwd is not None and not candidate.is_absolute():
            candidate = Path(cwd) / candidate
        # No filesystem access: policy decisions must stay pure, and a
        # path that does not exist yet is exactly what a write creates.
        normalized = _normalize(candidate)
        if normalized not in resolved:
            resolved.append(normalized)
    return CommandIntent(
        program=program, flags=tuple(flags), operands=tuple(operands),
        resolved_paths=tuple(resolved),
        cwd=_normalize(Path(cwd)) if cwd is not None else None,
        flag_values=tuple(flag_values),
        unexpanded=tuple(unexpanded),
    )


def _tokenize(command: str) -> list[str]:
    """Tokenize a shell string with quotes REMOVED and backslashes kept.

    `shlex.split(posix=False)` leaves the quote characters inside the
    token, so `"/etc"` stops looking absolute and gets anchored under the
    workspace — a one-character bypass of every path rule (adversarial
    review, reproduced). Plain `posix=True` fixes that but eats Windows
    backslashes (`C:\\Windows\\x` → `C:Windowsx`), which is the same bug
    wearing a different hat. Disabling escape processing gives both.
    """
    lexer = shlex.shlex(command, posix=True)
    lexer.whitespace_split = True
    lexer.escape = ""       # keep `\` literal: Windows paths survive
    lexer.commenters = ""   # `#` is a legal character in a path
    try:
        return list(lexer)
    except ValueError as exc:
        # An unbalanced quote is malformed input, not a parse we may guess
        # at: raising a typed error keeps the caller fail-closed.
        raise PolicyError(f"cannot tokenize command: {exc}") from exc


def _split_attached_value(token: str) -> tuple[str, str | None]:
    """Split `--output=/etc/x` and the separator-less `-o/etc/x`.

    curl/gcc/tar/find all accept `-o<value>`; treating it as an opaque
    flag hid its path from every rule (adversarial review).
    """
    if "=" in token:
        name, _, value = token.partition("=")
        return name, value or None
    if (len(token) > 2 and not token.startswith("--")
            and _looks_like_path(token[2:])):
        return token[:2], token[2:]
    return token, None


_EXPANSION_RE = re.compile(r"(^~)|(\$\w+)|(\$\{)|(%\w+%)")


def _needs_shell_expansion(token: str) -> bool:
    return bool(_EXPANSION_RE.search(token))


def _looks_like_path(token: str) -> bool:
    return ("/" in token or "\\" in token or token in (".", "..")
            or (len(token) > 1 and token[1] == ":"))


def _normalize(path: Path) -> str:
    r"""Lexical normalization into a canonical identity.

    No symlink resolution (that needs the disk and would break purity),
    but everything that can be decided lexically is: `..` collapsing that
    does NOT cancel a preserved `..` against another, and Windows
    aliasing (case, `\\?\` prefixes, trailing dots/spaces) folded so one
    real file has ONE identity — otherwise an approval or an allowlist
    keyed on the string is trivially side-stepped by respelling
    (adversarial review).
    """
    text = str(path).replace("\\", "/")
    # `\\?\C:\x` and `\\?\UNC\host\share` are alternate spellings of the
    # same target; strip the prefix before anything else looks at it.
    # pathlib may collapse the leading pair, so accept both spellings.
    for unc_prefix in ("//?/UNC/", "/?/UNC/"):
        if text.startswith(unc_prefix):
            text = "//" + text[len(unc_prefix):]
            break
    else:
        for prefix in ("//?/", "/?/"):
            if text.startswith(prefix):
                text = text[len(prefix):]
                break
    windows_style = len(text) > 1 and text[1] == ":"
    pure = PureWindowsPath(text) if windows_style else PurePosixPath(text)
    parts: list[str] = []
    for raw_part in pure.parts:
        part = raw_part
        if windows_style and part not in (pure.anchor,):
            # NTFS silently drops trailing dots and spaces, so `x.` and
            # `x ` open the same file as `x`.
            part = part.rstrip(". ") or part
        if part == "..":
            # Only pop a segment that is a real name: popping a preserved
            # `..` made two different targets share one identity, and
            # erased leading traversal entirely when there was no anchor.
            if parts and parts[-1] not in ("", "/", "..", pure.anchor):
                parts.pop()
                continue
            parts.append(part)
            continue
        if part == ".":
            continue
        parts.append(part)
    if windows_style:
        # NTFS is case-insensitive: C:/Work and c:/work are one file.
        parts = [p.casefold() for p in parts]
    joined = "".join(parts[:1]) + "/".join(parts[1:]) if parts and parts[0].endswith(("/", "\\")) \
        else "/".join(parts)
    return joined.replace("\\", "/")


def deep_freeze(value: Any) -> Any:
    """Recursively make a JSON-ish structure immutable.

    ``@dataclass(frozen=True)`` freezes only the *binding*: a dict field
    stays mutable, so an approved action could be edited after approval
    while the approval still appeared to match (Codex review). Freezing
    the contents closes that.
    """
    if isinstance(value, dict):
        return MappingProxyType({k: deep_freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(deep_freeze(v) for v in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(deep_freeze(v) for v in value)
    return value


def _thaw(value: Any) -> Any:
    """Plain-Python view for hashing/serialization."""
    if isinstance(value, (MappingProxyType, dict)):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(v) for v in value]
    if isinstance(value, frozenset):
        return sorted(_thaw(v) for v in value)
    return value


@dataclass(frozen=True)
class ActionSnapshot:
    """The complete input to one policy decision.

    Complete is the operative word: the engine reads nothing else, so a
    snapshot is a self-contained, hashable record of exactly what was
    evaluated — which is what an approval binds to and what a later audit
    can re-evaluate. Contents are deep-frozen at construction, so what was
    approved cannot be edited afterwards.
    """

    intervention_point: str
    tool: str
    actor: str
    intent: CommandIntent | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", deep_freeze(dict(self.payload)))
        object.__setattr__(self, "context", deep_freeze(dict(self.context)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "intervention_point": self.intervention_point, "tool": self.tool,
            "actor": self.actor,
            "intent": self.intent.to_dict() if self.intent else None,
            "payload": _thaw(self.payload), "context": _thaw(self.context),
        }

    def action_id(self) -> str:
        """sha256 identity of exactly this action (kernel.canonical)."""
        return hash_canonical(self.to_dict())


@dataclass(frozen=True)
class PolicyDecision:
    verdict: Verdict
    reason: str
    rule_id: str
    action_id: str
    detail: dict[str, Any] = field(default_factory=dict)
    transform: dict[str, Any] | None = None

    @property
    def is_runtime_error(self) -> bool:
        """True when this deny came from the engine failing, not from a
        policy deciding — never conflate the two."""
        return self.reason.startswith("runtime_error:")

    @property
    def is_policy_gap(self) -> bool:
        """True when this deny came from missing configuration."""
        return self.reason.startswith("policy_gap:")

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value, "reason": self.reason,
            "rule_id": self.rule_id, "action_id": self.action_id,
            "detail": self.detail, "transform": self.transform,
        }


# A rule is a pure function: snapshot -> decision-or-None (None = "no
# opinion"). Rules never mutate anything and never see the other rules.
Rule = Callable[[ActionSnapshot], "RuleOutcome | None"]


@dataclass(frozen=True)
class RuleOutcome:
    verdict: Verdict
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)
    transform: dict[str, Any] | None = None


@dataclass(frozen=True)
class InterventionPoint:
    """A declared decision site and the tools allowed to reach it."""

    name: str
    declared_tools: frozenset[str]
    rules: tuple[tuple[str, Rule], ...] = ()   # (rule_id, rule)
    # When the point's rules reason about a parsed command, a snapshot
    # without one is an INCOMPLETE snapshot, and the contract says
    # adapters build complete ones. Declaring the requirement lets the
    # engine deny instead of letting intent-keyed rules see nothing and
    # cheerfully allow (adversarial review).
    requires_intent: bool = False


class PolicyEngine:
    """Pure, stateless evaluator. One snapshot in, exactly one verdict out."""

    def __init__(self, intervention_points: Sequence[InterventionPoint]):
        self._points: dict[str, InterventionPoint] = {}
        for point in intervention_points:
            if point.name in self._points:
                # Last-wins would let a permissive registration silently
                # replace a strict one — a configuration gap converted
                # into consent (adversarial review).
                raise PolicyError(
                    f"duplicate intervention point {point.name!r}: refusing an "
                    "ambiguous policy configuration"
                )
            self._points[point.name] = point

    def decide(self, snapshot: ActionSnapshot) -> PolicyDecision:
        try:
            action_id = snapshot.action_id()
        except (TypeError, ValueError) as exc:
            # decide() must be TOTAL: hashing an unserializable payload
            # (NaN, bytes, a Path, non-str dict keys — all reachable from
            # agent-supplied JSON) used to raise straight out of the gate,
            # leaving the caller to decide what an exception means
            # (adversarial review). It means deny.
            return PolicyDecision(
                Verdict.DENY, "runtime_error:unhashable_snapshot",
                rule_id="engine", action_id="",
                detail={"error": repr(exc)[:200]},
            )

        point = self._points.get(snapshot.intervention_point)
        if point is None:
            # Silence is not permission: an intervention point nobody
            # configured is a configuration gap, and gaps deny.
            return PolicyDecision(
                Verdict.DENY,
                "policy_gap:unconfigured_intervention_point",
                rule_id="engine", action_id=action_id,
                detail={"intervention_point": snapshot.intervention_point},
            )
        if snapshot.tool not in point.declared_tools:
            return PolicyDecision(
                Verdict.DENY, "policy_gap:undeclared_tool",
                rule_id="engine", action_id=action_id,
                detail={"tool": snapshot.tool,
                        "declared": sorted(point.declared_tools)},
            )
        if point.requires_intent and snapshot.intent is None:
            return PolicyDecision(
                Verdict.DENY, "policy_gap:incomplete_snapshot",
                rule_id="engine", action_id=action_id,
                detail={"missing": "intent"},
            )

        best: PolicyDecision | None = None
        transforms: list[PolicyDecision] = []
        suppressed: list[dict[str, Any]] = []
        for rule_id, rule in point.rules:
            decision = self._evaluate(rule_id, rule, snapshot, action_id)
            if decision is None:
                continue
            if decision.verdict is Verdict.DENY and decision.is_runtime_error:
                # A broken rule cannot be outvoted: if the engine cannot
                # trust one opinion it does not get to pretend the others
                # are a complete picture.
                return decision
            if decision.verdict is Verdict.TRANSFORM:
                transforms.append(decision)
            if best is None or _PRECEDENCE[decision.verdict] > _PRECEDENCE[best.verdict]:
                if best is not None:
                    suppressed.append(
                        {"rule_id": best.rule_id, "verdict": best.verdict.value,
                         "reason": best.reason},
                    )
                best = decision
            else:
                suppressed.append(
                    {"rule_id": decision.rule_id, "verdict": decision.verdict.value,
                     "reason": decision.reason},
                )

        if len(transforms) > 1:
            # Two rules demanding different rewrites is not a tie the
            # engine may break by precedence: silently applying one and
            # dropping the other's mitigation is a security decision made
            # by declaration order (adversarial review).
            return PolicyDecision(
                Verdict.DENY, "runtime_error:conflicting_transforms",
                rule_id="engine", action_id=action_id,
                detail={"rule_ids": [t.rule_id for t in transforms]},
            )

        if best is None:
            # No rule had an opinion. Default-allow here would make every
            # unwritten rule a permission; the floor is deny.
            return PolicyDecision(
                Verdict.DENY, "policy_gap:no_rule_matched",
                rule_id="engine", action_id=action_id,
            )
        if suppressed:
            # A WARN outranked by a DENY still happened; dropping it would
            # lose evidence the operator needs (adversarial review).
            return PolicyDecision(
                best.verdict, best.reason, rule_id=best.rule_id,
                action_id=best.action_id,
                detail={**best.detail, "suppressed": suppressed},
                transform=best.transform,
            )
        return best

    def _evaluate(self, rule_id: str, rule: Rule, snapshot: ActionSnapshot,
                  action_id: str) -> PolicyDecision | None:
        # Deliberately typed as untrusted: a rule is arbitrary caller code,
        # so its declared return type is a promise, not a guarantee. The
        # isinstance check below is load-bearing defense, not dead code.
        outcome: Any
        try:
            outcome = rule(snapshot)
        except Exception as exc:  # noqa: BLE001 - a raising rule is a deny, never a skip
            return PolicyDecision(
                Verdict.DENY, "runtime_error:rule_raised", rule_id=rule_id,
                action_id=action_id, detail={"error": repr(exc)},
            )
        if outcome is None:
            return None
        # Validate the CONTENTS, not just the container: a RuleOutcome with
        # a string verdict used to reach _PRECEDENCE[...] and raise a
        # KeyError out of decide() entirely — the engine crashing instead
        # of denying (Codex review).
        if (not isinstance(outcome, RuleOutcome)
                or not isinstance(outcome.verdict, Verdict)
                or not isinstance(outcome.reason, str)
                or not outcome.reason
                or not isinstance(outcome.detail, dict)
                or (outcome.transform is not None
                    and not isinstance(outcome.transform, dict))):
            return PolicyDecision(
                Verdict.DENY, "runtime_error:invalid_rule_output", rule_id=rule_id,
                action_id=action_id, detail={"returned": repr(outcome)[:200]},
            )
        if outcome.reason.startswith(RESERVED_REASON_PREFIXES):
            # A rule that emits a reserved reason could disguise a policy
            # deny as an engine failure (or vice versa). Refuse the output.
            return PolicyDecision(
                Verdict.DENY, "runtime_error:reserved_reason_namespace",
                rule_id=rule_id, action_id=action_id,
                detail={"attempted_reason": outcome.reason},
            )
        if outcome.verdict is Verdict.TRANSFORM and outcome.transform is None:
            return PolicyDecision(
                Verdict.DENY, "runtime_error:transform_without_payload",
                rule_id=rule_id, action_id=action_id,
            )
        return PolicyDecision(
            outcome.verdict, outcome.reason, rule_id=rule_id, action_id=action_id,
            detail=outcome.detail, transform=outcome.transform,
        )


# -- approvals (state, deliberately outside the pure engine) ---------------


@dataclass(frozen=True)
class Approval:
    action_id: str
    approver: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"action_id": self.action_id, "approver": self.approver,
                "note": self.note}


class ApprovalStore:
    """Approvals bound to an exact action identity.

    A human approves *this* action — this program, these flags, these
    resolved paths, this payload — not "an action of roughly this shape".
    Any change produces a different action_id and the approval no longer
    applies, which is the anti-TOCTOU property.
    """

    def __init__(self) -> None:
        self._granted: dict[str, Approval] = {}

    def grant(self, action_id: str, approver: str, note: str = "") -> Approval:
        approval = Approval(action_id=action_id, approver=approver, note=note)
        self._granted[action_id] = approval
        return approval

    def revoke(self, action_id: str) -> None:
        self._granted.pop(action_id, None)

    def approval_for(self, snapshot: ActionSnapshot) -> Approval | None:
        try:
            action_id = snapshot.action_id()
        except (TypeError, ValueError):
            # An unhashable snapshot has no identity, so it can hold no
            # approval — never treat "cannot compute" as "approved".
            return None
        return self._granted.get(action_id)

    def is_approved(self, snapshot: ActionSnapshot) -> bool:
        return self.approval_for(snapshot) is not None


def resolve_escalation(decision: PolicyDecision, snapshot: ActionSnapshot,
                       approvals: ApprovalStore) -> PolicyDecision:
    """Turn an ESCALATE into ALLOW only when a matching approval exists.

    Non-escalations pass through untouched: an approval can never upgrade
    a DENY.
    """
    try:
        snapshot_id = snapshot.action_id()
    except (TypeError, ValueError) as exc:
        return PolicyDecision(
            Verdict.DENY, "runtime_error:unhashable_snapshot",
            rule_id=decision.rule_id, action_id="",
            detail={"error": repr(exc)[:200]},
        )
    if decision.action_id != snapshot_id:
        # The decision and the snapshot describe DIFFERENT actions: the
        # approval would be looked up for one and granted to the other
        # (Codex review). Refuse rather than reconcile.
        return PolicyDecision(
            Verdict.DENY, "runtime_error:decision_snapshot_mismatch",
            rule_id=decision.rule_id, action_id=snapshot_id,
            detail={"decision_action_id": decision.action_id},
        )
    if decision.verdict is not Verdict.ESCALATE:
        return decision
    approval = approvals.approval_for(snapshot)
    if approval is None:
        return decision
    return PolicyDecision(
        Verdict.ALLOW, f"approved:{decision.reason}", rule_id=decision.rule_id,
        action_id=decision.action_id,
        detail={**decision.detail, "approver": approval.approver,
                "approved_action_id": approval.action_id},
    )


# -- enforcement honesty ---------------------------------------------------


class EnforcementLevel(str, Enum):
    HARD = "HARD"                      # mechanically enforced by the OS/tool
    SANDBOX_APPROX = "SANDBOX_APPROX"  # approximated by a sandbox boundary
    PROMPT_ONLY = "PROMPT_ONLY"        # asked for, not enforced
    IGNORED = "IGNORED"                # declared but not implemented at all


@dataclass(frozen=True)
class EnforcementClaim:
    adapter: str
    restriction: str
    level: EnforcementLevel
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"adapter": self.adapter, "restriction": self.restriction,
                "level": self.level.value, "note": self.note}


class EnforcementMatrix:
    """Per-adapter record of how each restriction is actually enforced.

    Least-privilege decisions are only as good as the honesty of this
    table, so it is data a test can check — not a paragraph in a README
    that quietly rots.
    """

    def __init__(self, claims: Sequence[EnforcementClaim] = ()):
        self._claims: dict[tuple[str, str], EnforcementClaim] = {}
        for claim in claims:
            self.declare(claim)

    def declare(self, claim: EnforcementClaim) -> None:
        key = (claim.adapter, claim.restriction)
        if key in self._claims:
            raise PolicyError(
                f"duplicate enforcement claim for {claim.adapter}/{claim.restriction}"
            )
        self._claims[key] = claim

    def level_for(self, adapter: str, restriction: str) -> EnforcementLevel:
        """Undeclared means unknown, and unknown is never coerced to safe:
        an unrecorded restriction is reported as IGNORED."""
        claim = self._claims.get((adapter, restriction))
        return claim.level if claim else EnforcementLevel.IGNORED

    def claims(self) -> list[EnforcementClaim]:
        return sorted(self._claims.values(), key=lambda c: (c.adapter, c.restriction))

    def undeclared(self, adapter: str, restrictions: Sequence[str]) -> list[str]:
        """Restrictions an adapter is expected to cover but never declared."""
        return [r for r in restrictions if (adapter, r) not in self._claims]

    def not_mechanically_enforced(self) -> list[EnforcementClaim]:
        """Everything the kernel must NOT treat as a real boundary."""
        return [c for c in self.claims() if c.level is not EnforcementLevel.HARD]

    def verify(self, probes: Mapping[tuple[str, str], EnforcementProbe]) -> list[str]:
        """Check claims against EVIDENCE and return the contradictions.

        A label registry nobody falsifies is documentation with extra
        steps (Codex review): a probe empirically answers "can this
        restriction actually be escaped right now?", and a claim of HARD
        that a probe escapes is a lie the kernel would otherwise consume
        as a security boundary.

        Returns human-readable contradiction strings; empty means every
        probed claim matched observed reality.
        """
        problems: list[str] = []
        for (adapter, restriction), probe in probes.items():
            claim = self._claims.get((adapter, restriction))
            if claim is None:
                problems.append(
                    f"{adapter}/{restriction}: probed but never declared"
                )
                continue
            try:
                escaped = probe()
            except Exception as exc:  # noqa: BLE001 - an unrunnable probe proves nothing
                problems.append(f"{adapter}/{restriction}: probe failed: {exc!r}")
                continue
            if escaped and claim.level is EnforcementLevel.HARD:
                problems.append(
                    f"{adapter}/{restriction}: claimed HARD but the probe escaped it"
                )
            if not escaped and claim.level is EnforcementLevel.IGNORED:
                problems.append(
                    f"{adapter}/{restriction}: claimed IGNORED but the probe "
                    "could not escape it (claim may be stale)"
                )
        return problems

    def to_dict(self) -> dict[str, Any]:
        return {"claims": [c.to_dict() for c in self.claims()]}


# A probe returns True when the restriction CAN be escaped (i.e. is not
# actually enforced) and False when it holds.
EnforcementProbe = Callable[[], bool]


# The kernel's own enforcement claims: one source of truth the tests
# check, rather than a table restated inside each test. Every entry cites
# the ADR that establishes it.
GNOSIS_ENFORCEMENT = EnforcementMatrix([
    EnforcementClaim(
        "worktree", "shared_repo_isolation", EnforcementLevel.SANDBOX_APPROX,
        note="cwd scope only; an absolute path escapes it (ADR-0009 §1)",
    ),
    EnforcementClaim(
        "worktree", "orphaned_child_termination", EnforcementLevel.IGNORED,
        note="cooperative cancellation only, no job object (ADR-0009 residual)",
    ),
    EnforcementClaim(
        "file_lock", "single_writer", EnforcementLevel.HARD,
        note="OS advisory lock, cross-process and cross-thread (ADR-0004)",
    ),
    EnforcementClaim(
        "replay", "no_network_in_strict_replay", EnforcementLevel.HARD,
        note="live_fn is never invoked on a miss (ADR-0010)",
    ),
    EnforcementClaim(
        "claims", "no_stale_write_after_deposition", EnforcementLevel.HARD,
        note="guarded run-store boundary re-proves ownership (ADR-0006/0009)",
    ),
    EnforcementClaim(
        "policy", "deny_by_default", EnforcementLevel.HARD,
        note="unconfigured point / undeclared tool / no rule all deny (ADR-0011)",
    ),
    EnforcementClaim(
        "policy", "rule_purity", EnforcementLevel.IGNORED,
        note=(
            "rules are in-process operator code: a rule body can spawn a "
            "process or write the repo BEFORE returning its verdict, and "
            "nothing here stops it (Codex review, ADR-0013). The rule set "
            "is trusted configuration, at the same privilege as the kernel"
        ),
    ),
    EnforcementClaim(
        "convergence", "reviewer_read_only", EnforcementLevel.SANDBOX_APPROX,
        note=(
            "the review agent runs with edit tools withheld (a permission "
            "promise, not a sandbox), and the adapter fingerprints the tree "
            "either side and refuses a reviewer that moved it — detection "
            "after the fact, not prevention (ADR-0015, rule 9)"
        ),
    ),
    EnforcementClaim(
        "integration", "verified_before_landing", EnforcementLevel.HARD,
        note=(
            "ORDERING is mechanically enforced: the target advances only "
            "by fast-forward to a commit whose merged tree already ran the "
            "configured verifier and passed, from a base re-read under the "
            "lock immediately before the advance (ADR-0018)"
        ),
    ),
    EnforcementClaim(
        "integration", "semantic_correctness", EnforcementLevel.IGNORED,
        note=(
            "what 'verified' MEANS is the operator's verifier, not the "
            "kernel's judgement. A command that exits zero without looking "
            "at the merged files lets a broken tree land; the kernel "
            "cannot tell. Rule 16 is answered by the ordering claim above, "
            "not by this one (ADR-0018, Codex review)"
        ),
    ),
    EnforcementClaim(
        "integration", "shared_branch_gate", EnforcementLevel.PROMPT_ONLY,
        note=(
            "moving the shared branch is gated at its own intervention "
            "point, `before_integration` — but opt-in, like every other "
            "gate here, until a default rule set exists (ADR-0018, rule 13)"
        ),
    ),
    EnforcementClaim(
        "convergence", "reviewer_independence", EnforcementLevel.SANDBOX_APPROX,
        note=(
            "the pipeline refuses the SAME runner object for implementing "
            "and reviewing, which catches the degenerate case; it cannot "
            "verify that a different object is a different mind, so same "
            "provider and same model is still weak independence "
            "(ADR-0017, rule 10)"
        ),
    ),
    EnforcementClaim(
        "convergence", "verifier_execution", EnforcementLevel.IGNORED,
        note=(
            "verifier subprocesses run OUTSIDE the policy gate and the "
            "rate-limit hold, deliberately: a policy able to deny "
            "verification could switch off the evidence requirement that "
            "makes a DONE claim checkable. It is operator-configured, not "
            "agent-chosen (ADR-0017)"
        ),
    ),
    EnforcementClaim(
        "policy", "agent_launch_gate", EnforcementLevel.PROMPT_ONLY,
        note=(
            "opt-in: a TaskEngine or DirectorOrchestrator built without a "
            "policy launches agents with no verdict. Ungoverned runs record "
            "policy.ungoverned; require_policy=True makes it fail closed "
            "(ADR-0013)"
        ),
    ),
])
