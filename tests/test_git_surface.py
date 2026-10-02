"""F-17 Stage 7 — the closed-world .git surface classifier.

These tests pin the properties the mandate makes non-negotiable: three classes
and no fourth, UNKNOWN as the only catch-all, order-independence, overlap
rejection, a known parent never absorbing an unknown child, and a Windows
spelling never bypassing classification.
"""
from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gnosis.kernel import git_surface
from gnosis.kernel.git_surface import (
    RULES,
    GitSurfaceClass,
    GitSurfaceOverlap,
    _Rule,
    classify_git_surface,
    in_git_domain,
    rule_matrix,
)

TS = GitSurfaceClass.KNOWN_TRUST_SENSITIVE
BK = GitSurfaceClass.KNOWN_CONTENT_OR_BOOKKEEPING
UK = GitSurfaceClass.UNKNOWN


def _cls(path: str) -> GitSurfaceClass:
    return classify_git_surface(path).surface_class


class TestTheThreeClasses(unittest.TestCase):
    def test_trust_sensitive_surfaces(self):
        for path in (".git/config", ".git/config.worktree", ".git/HEAD",
                     ".git/packed-refs", ".git/shallow", ".git/commondir",
                     ".git/info/grafts", ".git/info/exclude", ".git/info/attributes",
                     ".git/objects/info/alternates",
                     ".git/objects/info/http-alternates",
                     ".git/refs/replace/aabb", ".git/refs/heads/main",
                     ".git/refs/tags/v1", ".git/refs/remotes/origin/main",
                     ".git/hooks/pre-commit", ".git/hooks/post-receive"):
            with self.subTest(path=path):
                self.assertIs(_cls(path), TS)

    def test_content_or_bookkeeping_surfaces(self):
        for path in (".git/index", ".git/index.lock",
                     ".git/sharedindex." + "a" * 40,
                     ".git/objects/ab/" + "c" * 38,
                     ".git/objects/de/" + "f" * 62,  # sha-256 loose object
                     ".git/objects/pack/pack-" + "a" * 40 + ".pack",
                     ".git/objects/pack/pack-" + "a" * 40 + ".idx",
                     ".git/logs/HEAD", ".git/logs/refs/heads/main",
                     ".git/COMMIT_EDITMSG", ".git/description",
                     ".git/hooks/pre-commit.sample"):
            with self.subTest(path=path):
                self.assertIs(_cls(path), BK)

    def test_unknown_surfaces_fail_closed(self):
        for path in (".git/refs/codex/x", ".git/refs/notes/commits",
                     ".git/objects/info/commit-graph", ".git/objects/info/packs",
                     ".git/objects/info/commit-graphs/z", ".git/worktrees/w/HEAD",
                     ".git/modules/m/config", ".git/ORIG_HEAD", ".git/FETCH_HEAD",
                     ".git/MERGE_HEAD", ".git/reftable/tables.list",
                     ".git/sparse-checkout", ".git/whatever-2030", ".git"):
            with self.subTest(path=path):
                self.assertIs(_cls(path), UK)

    def test_there_is_no_fourth_class(self):
        for path in (".git/config", ".git/index", ".git/unknown-thing"):
            self.assertIn(_cls(path), (TS, BK, UK))


class TestUnknownIsTheOnlyCatchAll(unittest.TestCase):
    def test_a_non_git_path_is_not_in_the_domain(self):
        for path in ("src/config", ".gitignore", ".gitmodules", "config",
                     "gitfoo/config"):
            with self.subTest(path=path):
                self.assertFalse(in_git_domain(path))

    def test_a_non_domain_path_classifies_unknown_not_git(self):
        v = classify_git_surface("src/config")
        self.assertIs(v.surface_class, UK)
        self.assertEqual(v.rule_id, "not-git-domain")


class TestKnownParentDoesNotAbsorbUnknownChild(unittest.TestCase):
    """known parent + unknown child != known child."""

    def test_objects_parent_does_not_absorb_objects_info(self):
        self.assertIs(_cls(".git/objects/ab/" + "c" * 38), BK)     # a real child
        self.assertIs(_cls(".git/objects/info/commit-graph"), UK)  # unknown sibling
        self.assertIs(_cls(".git/objects/newthing"), UK)

    def test_refs_parent_does_not_absorb_unknown_namespace(self):
        self.assertIs(_cls(".git/refs/heads/main"), TS)
        self.assertIs(_cls(".git/refs/codex/x"), UK)
        self.assertIs(_cls(".git/refs/future/x"), UK)

    def test_info_parent_does_not_absorb_unknown_child(self):
        self.assertIs(_cls(".git/info/exclude"), TS)
        self.assertIs(_cls(".git/info/refs"), UK)          # e.g. dumb-http
        self.assertIs(_cls(".git/info/sparse-checkout"), UK)

    def test_hooks_parent_does_not_absorb_a_subdirectory(self):
        self.assertIs(_cls(".git/hooks/pre-commit"), TS)
        self.assertIs(_cls(".git/hooks/sub/nested"), UK)   # not a flat hook name

    def test_a_new_nested_directory_under_a_known_parent_is_unknown(self):
        # The mandate's explicit case: a known .git parent + a brand-new nested
        # directory must be UNKNOWN, requiring zero special-case code.
        self.assertIs(_cls(".git/objects/futuredir/thing"), UK)
        # logs/ is qualified only for HEAD and refs/; a novel logs child is not
        # absorbed by the known parent — it is UNKNOWN, fail closed.
        self.assertIs(_cls(".git/logs/futuredir/thing"), UK)
        self.assertIs(_cls(".git/logs/other"), UK)


class TestOrderIndependence(unittest.TestCase):
    """No first-match security semantics: the result cannot depend on order."""

    _PROBES = (
        ".git/config", ".git/HEAD", ".git/refs/heads/main", ".git/index",
        ".git/objects/ab/" + "c" * 38, ".git/hooks/pre-commit",
        ".git/hooks/pre-commit.sample", ".git/refs/codex/x",
        ".git/objects/info/commit-graph", ".git/whatever",
    )

    def _classify_with_rules(self, rules, path):
        # Re-implement the collect-all semantics against an arbitrary rule order
        # to prove the module's result equals the order-free set result.
        from gnosis.kernel.git_surface import _canonical_remainder
        r = _canonical_remainder(path)
        if r is None:
            return UK
        matches = [rule for rule in rules if rule.matches(r)]
        if len(matches) > 1:
            raise GitSurfaceOverlap(path)
        return matches[0].surface_class if matches else UK

    def test_reversed_rule_order_gives_identical_classification(self):
        reversed_rules = tuple(reversed(RULES))
        for path in self._PROBES:
            with self.subTest(path=path):
                self.assertIs(self._classify_with_rules(reversed_rules, path),
                              _cls(path))

    def test_randomized_rule_orders_give_identical_classification(self):
        rng = random.Random(20260828)
        for _ in range(50):
            shuffled = list(RULES)
            rng.shuffle(shuffled)
            for path in self._PROBES:
                self.assertIs(self._classify_with_rules(tuple(shuffled), path),
                              _cls(path))


class TestOverlapIsRejected(unittest.TestCase):
    def test_two_rules_matching_one_path_raises(self):
        # Inject a rule that overlaps an existing one and prove classify refuses
        # rather than silently picking a winner.
        overlapping = _Rule("test.overlap", BK, "deliberately overlaps config",
                             lambda r: r == "config")
        original = git_surface.RULES
        try:
            git_surface.RULES = (*original, overlapping)
            with self.assertRaises(GitSurfaceOverlap):
                classify_git_surface(".git/config")
        finally:
            git_surface.RULES = original
        # and the real rule set does NOT raise for the same path
        self.assertIs(_cls(".git/config"), TS)

    def test_the_shipped_rule_set_is_internally_disjoint(self):
        # Every rule's own reason-bearing example must match exactly one rule.
        samples = {
            "config": 1, "config.worktree": 1, "head": 1, "packed-refs": 1,
            "shallow": 1, "commondir": 1, "info/grafts": 1, "info/exclude": 1,
            "info/attributes": 1, "objects/info/alternates": 1,
            "objects/info/http-alternates": 1, "refs/replace/x": 1,
            "refs/heads/main": 1, "refs/tags/v": 1, "refs/remotes/o/m": 1,
            "hooks/pre-commit": 1, "index": 1, "index.lock": 1,
            "sharedindex." + "a" * 40: 1, "objects/ab/" + "c" * 38: 1,
            "objects/pack/pack-" + "a" * 40 + ".pack": 1, "logs/head": 1,
            "logs/refs/heads/main": 1, "commit_editmsg": 1, "description": 1,
            "hooks/x.sample": 1,
        }
        for remainder, expected in samples.items():
            matches = [r.rule_id for r in RULES if r.matches(remainder)]
            with self.subTest(remainder=remainder):
                self.assertEqual(len(matches), expected,
                                 f"{remainder} matched {matches}")


class TestWindowsSpellingCannotBypass(unittest.TestCase):
    def test_case_variation_does_not_change_class(self):
        self.assertIs(_cls(".GIT/CONFIG"), TS)
        self.assertIs(_cls(".git/Config"), TS)
        self.assertIs(_cls(".git/HOOKS/Pre-Commit"), TS)
        self.assertIs(_cls(".git/INDEX"), BK)

    def test_backslashes_are_normalized(self):
        self.assertIs(_cls(".git\\config"), TS)
        self.assertIs(_cls(".git\\refs\\heads\\main"), TS)

    def test_trailing_dot_or_space_cannot_evade_an_exact_rule(self):
        # `config.` and `config ` open the same file on Windows.
        self.assertIs(_cls(".git/config."), TS)
        self.assertIs(_cls(".git/config "), TS)
        self.assertIs(_cls(".git/HEAD."), TS)

    def test_dot_components_fail_closed(self):
        self.assertIs(_cls(".git/refs/heads/../../config"), UK)
        self.assertIs(_cls(".git/./config"), UK)

    def test_a_stream_on_a_git_surface_is_classified_by_its_owner(self):
        self.assertIs(_cls(".git/config:$DATA"), TS)
        self.assertIs(_cls(".git/index:x"), BK)
        self.assertIs(_cls(".git/unknownthing:x"), UK)


class TestLockstepWithTheHistoricalPredicates(unittest.TestCase):
    """The classifier is now the authority; the old evidence_capture predicates
    are retained for their historical BLOCKER-A contract. This catches drift
    between the two catalogues: anything the old predicates judge dangerous must
    be TRUST_SENSITIVE in the classifier, or the two have diverged.
    """

    def test_every_predicate_flagged_surface_is_trust_sensitive(self):
        from gnosis.kernel.evidence_capture import (
            _is_git_machinery_tamper,
            _is_git_resolution_redirect,
        )
        surfaces = (".git/hooks/pre-commit", ".git/config", ".git/config:stream",
                    ".git/hooks/pre-push:x", ".git/refs/replace/abc",
                    ".git/packed-refs", ".git/packed-refs:s",
                    ".git/objects/info/alternates",
                    ".git/objects/info/http-alternates", ".git/info/grafts",
                    ".git/shallow", ".git/config.worktree", ".git/commondir")
        for path in surfaces:
            with self.subTest(path=path):
                flagged = (_is_git_machinery_tamper(path)
                           or _is_git_resolution_redirect(path))
                self.assertTrue(flagged, "predicate should flag this")
                self.assertIs(_cls(path), TS,
                              "classifier must agree the predicate-flagged "
                              "surface is trust-sensitive")


class TestTheMatrixIsAuditable(unittest.TestCase):
    def test_every_rule_has_a_stated_reason(self):
        for entry in rule_matrix():
            self.assertTrue(entry["reason"], entry["rule_id"])
            self.assertIn(entry["surface_class"], (TS.value, BK.value))

    def test_rule_ids_are_unique(self):
        ids = [r.rule_id for r in RULES]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
