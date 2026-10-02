"""Closed-world classification of `.git` administrative surfaces (F-17 Stage 7).

WHY THIS EXISTS. The evidence capture judges an allowlist of KNOWN-dangerous
`.git` surfaces (hooks, config, the resolution-redirect files) and, until this
module, forgave *everything else* under `.git/` as bookkeeping. That is an
inverted closed world: an administrative surface nobody had thought of — a
future Git namespace, a `refs/` namespace this project does not use, a control
file under `objects/info/` — read as benign by default. `UNKNOWN -> inert`.

Stage 7 inverts it. Every `.git` path belongs to EXACTLY ONE of three classes:

    KNOWN_TRUST_SENSITIVE          a write can change how Git RESOLVES or what it
                                   EXECUTES, in a way the capture's endpoints may
                                   not catch (an in-interval undo leaves them
                                   equal). Judged: the capture fails closed.
    KNOWN_CONTENT_OR_BOOKKEEPING   a write cannot change the trusted identity or
                                   resolution the evidence asserts, and the
                                   property WHY is stated on the rule. Counted,
                                   not judged.
    UNKNOWN                        everything else. There is no rule for it, so
                                   it is not qualified, so it fails closed. This
                                   is the whole point: a surface becomes allowed
                                   only by being moved, explicitly and with a
                                   stated property, into one of the known
                                   classes. `UNKNOWN -> MACHINERY_UNQUALIFIED`.

THE CLASSIFIER IS ORDER-INDEPENDENT BY CONSTRUCTION. It does not stop at the
first matching rule. It collects EVERY rule that matches and requires at most
one: two matches are a defect in the rule set, not a precedence puzzle to be
resolved by declaration order, so `classify` raises rather than silently
picking one. Zero matches is UNKNOWN. Reverse the rule list, shuffle it — the
result is identical, because a set has no order.

KNOWN PARENT + UNKNOWN CHILD != KNOWN CHILD. There is no `objects/**` or
`refs/**` blanket. Rules name QUALIFIED namespaces (`refs/heads/`, the loose
object shape `objects/<2hex>/<hex>`) so that a sibling under a known parent
(`refs/codex/x`, `objects/info/commit-graph`) matches nothing and is UNKNOWN.

WINDOWS SPELLING CANNOT BYPASS. The path is canonicalised before matching:
case-folded (NTFS is case-insensitive), separators unified, per-component
trailing dots and spaces stripped (Windows discards them), and any `.`/`..`
component makes the whole path UNKNOWN rather than letting a traversal spelling
reach a known rule. A residual remains — an 8.3 short name (`CONFIG~1`) that the
observer reports instead of the long name will not match an exact rule and so
falls to UNKNOWN; that is still fail-closed, and it is recorded as a residual
risk rather than papered over.

This module is pure: standard library only, no filesystem, no Git, no I/O. It
turns a path string into a class. The kernel imports it to judge write events;
the trust plane never imports it — it reads the recorded verdict from the
bundle, so the publisher's import closure is unchanged.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class GitSurfaceClass(Enum):
    """The three, and only three, classes a `.git` surface may hold."""

    KNOWN_TRUST_SENSITIVE = "KNOWN_TRUST_SENSITIVE"
    KNOWN_CONTENT_OR_BOOKKEEPING = "KNOWN_CONTENT_OR_BOOKKEEPING"
    UNKNOWN = "UNKNOWN"


class GitSurfaceOverlap(RuntimeError):
    """Two rules matched one path. A defect in the rule set, surfaced loudly.

    Raised rather than resolved: the moment classification depends on which
    rule was written first, the closed world is a fiction. A test feeds
    deliberately overlapping rules and asserts this is raised.
    """


@dataclass(frozen=True)
class GitSurfaceVerdict:
    """The structured result of a classification."""

    surface_class: GitSurfaceClass
    rule_id: str
    reason: str
    canonical_path: str  # the `.git`-relative remainder the decision was made on

    @property
    def is_qualified(self) -> bool:
        return self.surface_class is not GitSurfaceClass.UNKNOWN

    def to_dict(self) -> dict[str, str]:
        return {
            "surface_class": self.surface_class.value,
            "rule_id": self.rule_id,
            "reason": self.reason,
            "canonical_path": self.canonical_path,
        }


@dataclass(frozen=True)
class _Rule:
    rule_id: str
    surface_class: GitSurfaceClass
    reason: str
    matches: Callable[[str], bool]


def _exact(value: str) -> Callable[[str], bool]:
    return lambda r: r == value


def _prefix(value: str) -> Callable[[str], bool]:
    # A namespace: the value ends in '/', and the child must be non-empty so the
    # bare namespace directory itself does not match a child rule.
    return lambda r: r.startswith(value) and len(r) > len(value)


def _regex(pattern: str) -> Callable[[str], bool]:
    compiled = re.compile(pattern)
    return lambda r: compiled.fullmatch(r) is not None


# The object-name shapes Git actually uses: SHA-1 (40 hex, 2+38) and SHA-256
# (64 hex, 2+62). A loose object's NAME is the hash of its bytes, so it cannot be
# made to name different content — which is exactly the property that lets it be
# bookkeeping rather than trust-sensitive.
_LOOSE_OBJECT = r"objects/[0-9a-f]{2}/(?:[0-9a-f]{38}|[0-9a-f]{62})"
_PACK_FILE = r"objects/pack/pack-[0-9a-f]{40,64}\.(?:pack|idx|rev|mtimes|keep|bitmap)"
_SHARED_INDEX = r"sharedindex\.[0-9a-f]{40,64}"
_HOOK = r"hooks/[^/]+"
_HOOK_SAMPLE = r"hooks/[^/]+\.sample"


# ---------------------------------------------------------------------------
# THE RULE SET. This IS the semantic matrix. Every entry states the property
# it relies on. Order is irrelevant (see module docstring); it is grouped for
# a reader, not for precedence.
# ---------------------------------------------------------------------------
_TS = GitSurfaceClass.KNOWN_TRUST_SENSITIVE
_BK = GitSurfaceClass.KNOWN_CONTENT_OR_BOOKKEEPING

RULES: tuple[_Rule, ...] = (
    # -- resolution / execution surfaces: a write can change what Git runs or
    #    how it resolves objects/refs/ancestry, and an in-interval undo would
    #    leave the before/after endpoints equal. Judged.
    _Rule("ts.config", _TS,
          "config selects filters, hooksPath, alternates, worktree and "
          "extensions — it can redirect resolution and execution",
          _exact("config")),
    _Rule("ts.config-worktree", _TS,
          "per-worktree config (extensions.worktreeConfig) sets executable keys "
          "like core.fsmonitor",
          _exact("config.worktree")),
    _Rule("ts.head", _TS,
          "HEAD is the symbolic ref that defines the checked-out commit; a "
          "write changes what every `HEAD`-relative read resolves to",
          _exact("head")),
    _Rule("ts.packed-refs", _TS,
          "the packed form of the ref backend; a write moves what refs resolve "
          "to (the packed twin of the loose refs/ rules)",
          _exact("packed-refs")),
    _Rule("ts.shallow", _TS,
          "grafts the history boundary; changes ancestry resolution",
          _exact("shallow")),
    _Rule("ts.commondir", _TS,
          "redirects the common dir — the root of ref/object resolution",
          _exact("commondir")),
    _Rule("ts.info-grafts", _TS,
          "fabricates commit parentage; changes ancestry resolution",
          _exact("info/grafts")),
    _Rule("ts.info-exclude", _TS,
          "steers what Git enumerates as ignored/untracked, which shapes the "
          "covered-input set and the content fingerprint's untracked hashes",
          _exact("info/exclude")),
    _Rule("ts.info-attributes", _TS,
          "drives clean/smudge filters and diff behaviour, so it can change "
          "what `git diff HEAD` reports for the same bytes",
          _exact("info/attributes")),
    _Rule("ts.objects-info-alternates", _TS,
          "redirects object lookup to an external store",
          _exact("objects/info/alternates")),
    _Rule("ts.objects-info-http-alternates", _TS,
          "redirects object lookup to an external (http) store",
          _exact("objects/info/http-alternates")),
    _Rule("ts.refs-replace", _TS,
          "replace refs substitute one object for another during resolution "
          "with the original bytes intact (BLOCKER A)",
          _prefix("refs/replace/")),
    _Rule("ts.refs-heads", _TS,
          "a branch ref is what HEAD resolves to; an in-interval write is the "
          "loose form of the packed-refs risk",
          _prefix("refs/heads/")),
    _Rule("ts.refs-tags", _TS,
          "a tag resolves to an object a check may read via `git rev-parse`",
          _prefix("refs/tags/")),
    _Rule("ts.refs-remotes", _TS,
          "a remote-tracking ref resolves to an object a check may read",
          _prefix("refs/remotes/")),
    _Rule("ts.hook", _TS,
          "a non-sample hook is code Git executes on the next operation",
          lambda r: bool(re.fullmatch(_HOOK, r)) and not r.endswith(".sample")),

    # -- content / bookkeeping surfaces: a write cannot change the trusted
    #    identity (working tree + resolved HEAD, bound at the endpoints) or the
    #    resolution the redirect rules already cover. Counted, not judged.
    _Rule("bk.index", _BK,
          "the staging/stat-cache index; the trusted identity is working-tree "
          "vs HEAD (`git diff HEAD`, index-independent) plus endpoint-captured "
          "`git status`, so an index write cannot alter identity without moving "
          "an endpoint the capture already binds",
          _exact("index")),
    _Rule("bk.index-lock", _BK,
          "the transient lock Git writes and removes around an index update",
          _exact("index.lock")),
    _Rule("bk.sharedindex", _BK,
          "the split-index backing file; same property as index — staging "
          "state, captured at the endpoints via `git status`",
          _regex(_SHARED_INDEX)),
    _Rule("bk.loose-object", _BK,
          "a content-addressed loose object: its name is the hash of its bytes, "
          "so it cannot be made to name different content; F-14 byte-binds "
          "tracked content and the redirect rules cover substitution",
          _regex(_LOOSE_OBJECT)),
    _Rule("bk.pack", _BK,
          "content-addressed pack data; same property as a loose object",
          _regex(_PACK_FILE)),
    _Rule("bk.reflog-head", _BK,
          "the HEAD reflog: an append-only record of ref movement, never "
          "consulted when resolving a ref to an object",
          _exact("logs/head")),
    _Rule("bk.reflog-refs", _BK,
          "a ref's reflog; append-only movement history, not consulted in "
          "ref->object resolution",
          _prefix("logs/refs/")),
    _Rule("bk.commit-editmsg", _BK,
          "the last commit message buffer; scratch, never consulted by "
          "resolution or by the trusted read",
          _exact("commit_editmsg")),
    _Rule("bk.description", _BK,
          "the human repo description (gitweb only); never consulted",
          _exact("description")),
    _Rule("bk.hook-sample", _BK,
          "an inert example hook Git ships; the `.sample` suffix means it is "
          "never executed",
          _regex(_HOOK_SAMPLE)),
)


def _canonical_remainder(owner_path: str) -> str | None:
    """The `.git`-relative remainder, canonicalised, or None if not `.git`.

    Returns the lowercased, separator-unified, trailing-dot/space-stripped path
    UNDER `.git` (e.g. ``config``, ``refs/heads/main``). Returns None when the
    path is not under `.git` at all (the caller then handles it as an ordinary
    path). A `.`/`..` component, or the bare `.git` directory itself, yields the
    empty string ``""`` — in the domain but matching no rule, hence UNKNOWN.
    """
    # Streams arrive as `owner:stream`; classify the owner. A repository-relative
    # path never otherwise contains a colon, so this is the ADS split, not a
    # heuristic — the same idiom the existing predicates use.
    owner = owner_path.split(":", 1)[0]
    owner = owner.replace("\\", "/")
    parts = [p for p in owner.split("/") if p != ""]
    if not parts:
        return None
    canon: list[str] = []
    for part in parts:
        stripped = part.rstrip(". ")  # Windows discards trailing dots and spaces
        lowered = stripped.lower()
        if lowered in ("", ".", ".."):
            # A dot component (or a component that WAS only dots/spaces) is a
            # traversal or ambiguity: refuse to let any spelling of it reach a
            # known rule. In the domain if it began with .git, else not.
            if canon and canon[0] == ".git":
                return ""  # in domain, unclassifiable -> UNKNOWN
            return None if not canon else ""
        canon.append(lowered)
    if canon[0] != ".git":
        return None
    return "/".join(canon[1:])


def in_git_domain(owner_path: str) -> bool:
    """True if the path is under `.git` (any spelling)."""
    return _canonical_remainder(owner_path) is not None


def classify_git_surface(owner_path: str) -> GitSurfaceVerdict:
    """Classify a `.git` path into exactly one class, order-independently.

    Precondition: the path is under `.git` (``in_git_domain`` is True). If it is
    not, this still returns a verdict (UNKNOWN, rule ``not-git-domain``) so a
    caller can never mistake a non-`.git` path for a qualified one.
    """
    remainder = _canonical_remainder(owner_path)
    if remainder is None:
        return GitSurfaceVerdict(
            GitSurfaceClass.UNKNOWN, "not-git-domain",
            "the path is not under .git", "")
    matches = [rule for rule in RULES if rule.matches(remainder)]
    if len(matches) > 1:
        raise GitSurfaceOverlap(
            f"{remainder!r} matched {[m.rule_id for m in matches]}; the rule "
            "set is not disjoint, which would make classification depend on "
            "order")
    if not matches:
        return GitSurfaceVerdict(
            GitSurfaceClass.UNKNOWN, "unqualified",
            "no rule qualifies this .git surface; it fails closed until one is "
            "added with a stated property", remainder)
    rule = matches[0]
    return GitSurfaceVerdict(rule.surface_class, rule.rule_id, rule.reason, remainder)


def rule_matrix() -> tuple[dict[str, str], ...]:
    """The semantic matrix, for evidence and review: every rule and its reason."""
    return tuple(
        {"rule_id": r.rule_id, "surface_class": r.surface_class.value,
         "reason": r.reason}
        for r in RULES
    )
