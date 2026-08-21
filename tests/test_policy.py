import unittest
from pathlib import Path

from gnosis.kernel.policy import (
    GNOSIS_ENFORCEMENT,
    ActionSnapshot,
    ApprovalStore,
    CommandIntent,
    EnforcementClaim,
    EnforcementLevel,
    EnforcementMatrix,
    InterventionPoint,
    PolicyEngine,
    PolicyError,
    RuleOutcome,
    Verdict,
    parse_command,
    resolve_escalation,
)


def _snapshot(tool: str = "bash", point: str = "before_tool",
              intent: CommandIntent | None = None, **payload) -> ActionSnapshot:
    return ActionSnapshot(
        intervention_point=point, tool=tool, actor="agent://worker-a",
        intent=intent or CommandIntent(program="echo", operands=("hi",)),
        payload=payload,
    )


def _allow_all(_: ActionSnapshot) -> RuleOutcome:
    return RuleOutcome(Verdict.ALLOW, "baseline:permitted")


def _engine(*rules, tools=("bash",), point="before_tool") -> PolicyEngine:
    return PolicyEngine([
        InterventionPoint(
            name=point, declared_tools=frozenset(tools),
            rules=tuple((f"rule-{i}", r) for i, r in enumerate(rules)),
        )
    ])


class TestCommandIntentParsing(unittest.TestCase):
    def test_flags_and_operands_are_separated(self):
        intent = parse_command(["rm", "-rf", "build"])
        self.assertEqual(intent.program, "rm")
        self.assertEqual(intent.flags, ("-rf",))
        self.assertEqual(intent.operands, ("build",))
        self.assertTrue(intent.has_flag("-rf"))

    def test_relative_paths_resolve_against_cwd(self):
        intent = parse_command(["cat", "notes/a.txt"], cwd=Path("/work/repo"))
        self.assertEqual(intent.resolved_paths, ("/work/repo/notes/a.txt",))

    def test_traversal_is_normalized_so_rules_see_the_real_target(self):
        # Substring matching on the raw token would miss this entirely.
        intent = parse_command(["cat", "../../etc/passwd"], cwd=Path("/work/repo"))
        self.assertEqual(intent.resolved_paths, ("/etc/passwd",))

    def test_empty_command_is_refused(self):
        with self.assertRaises(PolicyError):
            parse_command([])

    def test_attached_flag_values_are_visible_and_resolved(self):
        # `-o /etc/x` and `--output=/etc/x` mean the same thing; if only
        # the separated spelling reaches resolved_paths, the attached one
        # is a free bypass (verified before the fix).
        intent = parse_command(["curl", "--output=/etc/cron.d/x", "u"],
                               cwd=Path("/work/repo"))
        self.assertIn("/etc/cron.d/x", intent.resolved_paths)
        self.assertEqual(intent.value_for("--output"), "/etc/cron.d/x")
        self.assertTrue(intent.has_flag("--output"))  # either spelling

    def test_bare_operands_resolve_against_cwd(self):
        # `build` has no slash, but it is still a path.
        intent = parse_command(["rm", "-rf", "build"], cwd=Path("/work/repo"))
        self.assertEqual(intent.resolved_paths, ("/work/repo/build",))

    def test_cwd_is_part_of_the_intent(self):
        # The same argv in two directories is two different actions.
        here = parse_command(["rm", "-rf", "build"], cwd=Path("/work/repo"))
        there = parse_command(["rm", "-rf", "build"], cwd=Path("/production/live"))
        self.assertNotEqual(here.to_dict(), there.to_dict())
        self.assertEqual(here.cwd, "/work/repo")

    def test_quoting_cannot_hide_an_absolute_path(self):
        # One quote character used to flip DENY into ALLOW: posix=False
        # kept the quotes, so `"/etc"` stopped looking absolute and got
        # anchored inside the workspace (adversarial review, reproduced).
        for command in ('rm -rf "/etc"', "rm -rf '/etc'", 'cat "/etc/shadow"'):
            intent = parse_command(command, cwd=Path("/work/repo"))
            self.assertTrue(
                any(p.startswith("/etc") for p in intent.resolved_paths),
                msg=f"{command} -> {intent.resolved_paths}",
            )

    def test_quoting_cannot_hide_traversal_or_a_flag(self):
        traversal = parse_command('cat "../../etc/passwd"', cwd=Path("/work/repo"))
        self.assertIn("/etc/passwd", traversal.resolved_paths)
        flagged = parse_command('curl "--output=/etc/x" u', cwd=Path("/work/repo"))
        self.assertIn("/etc/x", flagged.resolved_paths)
        self.assertTrue(flagged.has_flag("--output"))

    def test_windows_backslash_paths_survive_tokenization(self):
        # The naive fix for the quote bug (posix=True) eats backslashes,
        # which is the same bypass wearing a different hat.
        intent = parse_command(r"cp x C:\Windows\System32\hosts")
        self.assertIn("c:/windows/system32/hosts", intent.resolved_paths)

    def test_unbalanced_quotes_are_a_typed_error_not_a_guess(self):
        with self.assertRaises(PolicyError):
            parse_command('rm -rf "/etc')

    def test_separatorless_short_flag_values_are_resolved(self):
        # curl/gcc/tar all accept -o<value>; treating it as an opaque flag
        # hid the path from every rule.
        intent = parse_command(["curl", "-o/etc/cron.d/x", "u"], cwd=Path("/work/repo"))
        self.assertIn("/etc/cron.d/x", intent.resolved_paths)
        self.assertEqual(intent.value_for("-o"), "/etc/cron.d/x")

    def test_shell_expansions_are_surfaced_not_laundered(self):
        # `~/.ssh/id_rsa` anchored under cwd became a FALSE in-workspace
        # path — manufacturing the very safety it was meant to check.
        for token in ("~/.ssh/id_rsa", "$HOME/.ssh/id_rsa", "%USERPROFILE%/x"):
            intent = parse_command(["cat", token], cwd=Path("/work/repo"))
            self.assertEqual(intent.unexpanded, (token,), msg=token)
            self.assertEqual(intent.resolved_paths, (), msg=token)

    def test_normalize_gives_one_identity_per_real_target(self):
        # An allowlist keyed on a string is worthless if the same file has
        # several spellings.
        from gnosis.kernel.policy import _normalize

        self.assertEqual(_normalize(Path("C:/Work/Repo./file ")),
                         _normalize(Path("c:/work/repo/file")))
        self.assertEqual(_normalize(Path(r"\\?\C:\Work\x")),
                         _normalize(Path("C:/Work/x")))

    def test_normalize_never_cancels_a_preserved_dotdot(self):
        from gnosis.kernel.policy import _normalize

        # `..` popping another `..` made two different targets share one
        # identity; erasing a leading `..` hid traversal entirely.
        self.assertEqual(_normalize(Path("../x")), "../x")
        self.assertNotEqual(_normalize(Path("../../x")), _normalize(Path("../x")))

    def test_double_dash_operands_still_resolve(self):
        intent = parse_command(["rm", "--", "/etc/passwd"], cwd=Path("/work/repo"))
        self.assertIn("/etc/passwd", intent.resolved_paths)


class TestFailClosedDefaults(unittest.TestCase):
    def test_unconfigured_intervention_point_denies(self):
        engine = PolicyEngine([])
        decision = engine.decide(_snapshot())
        self.assertEqual(decision.verdict, Verdict.DENY)
        self.assertEqual(decision.reason, "policy_gap:unconfigured_intervention_point")
        self.assertTrue(decision.is_policy_gap)

    def test_undeclared_tool_denies(self):
        decision = _engine(_allow_all, tools=("bash",)).decide(_snapshot(tool="curl"))
        self.assertEqual(decision.verdict, Verdict.DENY)
        self.assertEqual(decision.reason, "policy_gap:undeclared_tool")

    def test_no_matching_rule_denies(self):
        # An unwritten rule must never act as a permission.
        decision = _engine(lambda s: None).decide(_snapshot())
        self.assertEqual(decision.verdict, Verdict.DENY)
        self.assertEqual(decision.reason, "policy_gap:no_rule_matched")

    def test_unhashable_snapshot_denies_instead_of_raising(self):
        # decide() must be TOTAL: NaN is reachable from agent JSON
        # (json.loads accepts it), and the gate raising leaves the caller
        # to guess what an exception means (adversarial review).
        engine = _engine(_allow_all)
        for payload in ({"n": float("nan")}, {"b": b"x"}, {"p": Path("/x")}):
            decision = engine.decide(_snapshot(**payload))
            self.assertEqual(decision.verdict, Verdict.DENY, msg=repr(payload))
            self.assertEqual(decision.reason, "runtime_error:unhashable_snapshot")

    def test_duplicate_intervention_points_are_refused(self):
        # Last-wins would let a permissive registration silently replace a
        # strict one — a configuration gap turned into consent.
        with self.assertRaises(PolicyError):
            PolicyEngine([
                InterventionPoint("before_tool", frozenset({"bash"})),
                InterventionPoint("before_tool", frozenset({"bash", "curl"})),
            ])

    def test_a_point_requiring_intent_denies_an_intent_less_snapshot(self):
        engine = PolicyEngine([InterventionPoint(
            name="before_tool", declared_tools=frozenset({"bash"}),
            rules=(("allow", _allow_all),), requires_intent=True,
        )])
        snapshot = ActionSnapshot("before_tool", "bash", "agent://a", intent=None)
        decision = engine.decide(snapshot)
        self.assertEqual(decision.verdict, Verdict.DENY)
        self.assertEqual(decision.reason, "policy_gap:incomplete_snapshot")

    def test_engine_with_no_rules_denies(self):
        decision = _engine().decide(_snapshot())
        self.assertEqual(decision.verdict, Verdict.DENY)
        self.assertTrue(decision.is_policy_gap)


class TestRuntimeFailuresCollapseToDeny(unittest.TestCase):
    def test_raising_rule_denies_in_the_reserved_namespace(self):
        def boom(_: ActionSnapshot) -> RuleOutcome:
            raise ValueError("rule exploded")

        decision = _engine(boom).decide(_snapshot())
        self.assertEqual(decision.verdict, Verdict.DENY)
        self.assertEqual(decision.reason, "runtime_error:rule_raised")
        self.assertTrue(decision.is_runtime_error)
        self.assertIn("rule exploded", decision.detail["error"])

    def test_a_broken_rule_cannot_be_outvoted_by_healthy_ones(self):
        # If one opinion is untrustworthy, the remaining ones are not a
        # complete picture: the engine must not pretend otherwise.
        def boom(_: ActionSnapshot) -> RuleOutcome:
            raise ValueError("boom")

        decision = _engine(boom, _allow_all).decide(_snapshot())
        self.assertTrue(decision.is_runtime_error)

    def test_garbage_rule_output_denies(self):
        decision = _engine(lambda s: "yes please").decide(_snapshot())
        self.assertEqual(decision.verdict, Verdict.DENY)
        self.assertEqual(decision.reason, "runtime_error:invalid_rule_output")

    def test_rule_cannot_emit_a_reserved_reason(self):
        # Otherwise a policy deny could masquerade as an engine failure,
        # or an engine failure as a policy decision.
        for reason in ("runtime_error:faked", "policy_gap:faked"):
            decision = _engine(
                lambda s, r=reason: RuleOutcome(Verdict.DENY, r)
            ).decide(_snapshot())
            self.assertEqual(decision.reason, "runtime_error:reserved_reason_namespace")
            self.assertEqual(decision.detail["attempted_reason"], reason)

    def test_malformed_rule_outcome_contents_deny_instead_of_crashing(self):
        # A RuleOutcome whose verdict is a bare string used to reach the
        # precedence table and raise a KeyError OUT of decide() — the
        # engine crashing instead of denying (Codex review).
        broken = [
            RuleOutcome("ALLOW", "ok:fine"),          # verdict not an enum
            RuleOutcome(Verdict.ALLOW, 42),            # reason not a str
            RuleOutcome(Verdict.ALLOW, ""),            # empty reason
            RuleOutcome(Verdict.ALLOW, "ok:fine", detail="nope"),
            RuleOutcome(Verdict.TRANSFORM, "t:x", transform="nope"),
        ]
        for outcome in broken:
            decision = _engine(lambda s, o=outcome: o).decide(_snapshot())
            self.assertEqual(decision.verdict, Verdict.DENY, msg=repr(outcome))
            self.assertEqual(decision.reason, "runtime_error:invalid_rule_output")

    def test_transform_without_payload_denies(self):
        decision = _engine(
            lambda s: RuleOutcome(Verdict.TRANSFORM, "rewrite:safer")
        ).decide(_snapshot())
        self.assertEqual(decision.reason, "runtime_error:transform_without_payload")

    def test_policy_deny_is_distinguishable_from_engine_failure(self):
        policy = _engine(
            lambda s: RuleOutcome(Verdict.DENY, "network:egress_forbidden")
        ).decide(_snapshot())
        self.assertEqual(policy.verdict, Verdict.DENY)
        self.assertFalse(policy.is_runtime_error)
        self.assertFalse(policy.is_policy_gap)


class TestVerdictPrecedence(unittest.TestCase):
    def test_deny_beats_everything(self):
        decision = _engine(
            _allow_all,
            lambda s: RuleOutcome(Verdict.WARN, "style:suspicious"),
            lambda s: RuleOutcome(Verdict.DENY, "fs:outside_workspace"),
            lambda s: RuleOutcome(Verdict.ESCALATE, "human:needed"),
        ).decide(_snapshot())
        self.assertEqual(decision.verdict, Verdict.DENY)
        self.assertEqual(decision.reason, "fs:outside_workspace")

    def test_escalate_beats_warn_and_allow(self):
        decision = _engine(
            _allow_all,
            lambda s: RuleOutcome(Verdict.WARN, "style:suspicious"),
            lambda s: RuleOutcome(Verdict.ESCALATE, "human:needed"),
        ).decide(_snapshot())
        self.assertEqual(decision.verdict, Verdict.ESCALATE)

    def test_warn_beats_allow_and_proceeds(self):
        decision = _engine(
            _allow_all, lambda s: RuleOutcome(Verdict.WARN, "style:suspicious"),
        ).decide(_snapshot())
        self.assertEqual(decision.verdict, Verdict.WARN)

    def test_conflicting_transforms_deny_instead_of_picking_by_declaration_order(self):
        # Two rules demanding different rewrites is not a tie precedence
        # may break: dropping one mitigation silently is a security
        # decision made by tuple order (adversarial review).
        decision = _engine(
            lambda s: RuleOutcome(Verdict.TRANSFORM, "rewrite:a", transform={"cmd": "a"}),
            lambda s: RuleOutcome(Verdict.TRANSFORM, "rewrite:b", transform={"cmd": "b"}),
        ).decide(_snapshot())
        self.assertEqual(decision.verdict, Verdict.DENY)
        self.assertEqual(decision.reason, "runtime_error:conflicting_transforms")

    def test_an_outranked_warning_is_carried_not_erased(self):
        decision = _engine(
            lambda s: RuleOutcome(Verdict.WARN, "style:suspicious"),
            lambda s: RuleOutcome(Verdict.DENY, "fs:forbidden"),
        ).decide(_snapshot())
        self.assertEqual(decision.verdict, Verdict.DENY)
        suppressed = decision.detail["suppressed"]
        self.assertTrue(any(s["reason"] == "style:suspicious" for s in suppressed))

    def test_rule_id_provenance_is_carried(self):
        engine = PolicyEngine([InterventionPoint(
            name="before_tool", declared_tools=frozenset({"bash"}),
            rules=(("allow-baseline", _allow_all),
                   ("deny-egress", lambda s: RuleOutcome(Verdict.DENY, "network:blocked"))),
        )])
        decision = engine.decide(_snapshot())
        self.assertEqual(decision.rule_id, "deny-egress")


class TestPurityAndIdentity(unittest.TestCase):
    def test_same_snapshot_yields_the_same_decision(self):
        engine = _engine(lambda s: RuleOutcome(Verdict.ALLOW, "ok:fine"))
        snapshot = _snapshot()
        self.assertEqual(engine.decide(snapshot).to_dict(),
                         engine.decide(snapshot).to_dict())

    def test_action_id_changes_with_any_meaningful_field(self):
        base = _snapshot()
        variants = [
            _snapshot(tool="python"),
            _snapshot(intent=CommandIntent(program="rm", flags=("-rf",))),
            _snapshot(extra="payload"),
            ActionSnapshot(intervention_point="before_write", tool="bash",
                           actor="agent://worker-a", intent=base.intent),
            ActionSnapshot(intervention_point="before_tool", tool="bash",
                           actor="agent://worker-b", intent=base.intent),
        ]
        for variant in variants:
            self.assertNotEqual(base.action_id(), variant.action_id())

    def test_action_id_is_stable_across_key_order(self):
        a = _snapshot(alpha=1, beta=2)
        b = _snapshot(beta=2, alpha=1)
        self.assertEqual(a.action_id(), b.action_id())


class TestApprovalBinding(unittest.TestCase):
    def setUp(self):
        self.approvals = ApprovalStore()
        self.engine = _engine(
            lambda s: RuleOutcome(Verdict.ESCALATE, "human:destructive_action")
        )

    def test_escalation_stays_blocked_without_approval(self):
        snapshot = _snapshot()
        decision = resolve_escalation(self.engine.decide(snapshot), snapshot, self.approvals)
        self.assertEqual(decision.verdict, Verdict.ESCALATE)

    def test_approval_of_the_exact_action_allows_it(self):
        snapshot = _snapshot()
        self.approvals.grant(snapshot.action_id(), approver="nicol")
        decision = resolve_escalation(self.engine.decide(snapshot), snapshot, self.approvals)
        self.assertEqual(decision.verdict, Verdict.ALLOW)
        self.assertEqual(decision.detail["approver"], "nicol")
        self.assertTrue(decision.reason.startswith("approved:"))

    def test_approval_does_not_transfer_to_a_changed_action(self):
        # Anti-TOCTOU: approve `rm -rf build`, then try `rm -rf /`.
        approved = _snapshot(intent=parse_command(["rm", "-rf", "build"], cwd=Path("/w")))
        self.approvals.grant(approved.action_id(), approver="nicol")
        tampered = _snapshot(intent=parse_command(["rm", "-rf", "/"], cwd=Path("/w")))
        decision = resolve_escalation(self.engine.decide(tampered), tampered, self.approvals)
        self.assertEqual(decision.verdict, Verdict.ESCALATE)
        self.assertFalse(self.approvals.is_approved(tampered))

    def test_approval_never_upgrades_a_deny(self):
        engine = _engine(lambda s: RuleOutcome(Verdict.DENY, "fs:forbidden"))
        snapshot = _snapshot()
        self.approvals.grant(snapshot.action_id(), approver="nicol")
        decision = resolve_escalation(engine.decide(snapshot), snapshot, self.approvals)
        self.assertEqual(decision.verdict, Verdict.DENY)

    def test_decision_and_snapshot_must_describe_the_same_action(self):
        # Otherwise the approval is looked up for one action and granted
        # to another (Codex review).
        evaluated = _snapshot(intent=parse_command(["rm", "-rf", "build"],
                                                   cwd=Path("/work/repo")))
        other = _snapshot(intent=parse_command(["rm", "-rf", "/"],
                                               cwd=Path("/work/repo")))
        self.approvals.grant(other.action_id(), approver="nicol")
        decision = resolve_escalation(self.engine.decide(evaluated), other, self.approvals)
        self.assertEqual(decision.verdict, Verdict.DENY)
        self.assertEqual(decision.reason, "runtime_error:decision_snapshot_mismatch")

    def test_an_approved_action_cannot_be_edited_afterwards(self):
        # Shallow freezing left payload/context mutable, so an approved
        # action could be changed while the approval still matched.
        snapshot = _snapshot(target="/work/repo/safe.txt")
        self.approvals.grant(snapshot.action_id(), approver="nicol")
        with self.assertRaises(TypeError):
            snapshot.payload["target"] = "/etc/passwd"  # type: ignore[index]
        self.assertEqual(snapshot.payload["target"], "/work/repo/safe.txt")

    def test_nested_payload_is_frozen_too(self):
        snapshot = _snapshot(plan={"steps": [{"path": "/work/repo/a"}]})
        with self.assertRaises(TypeError):
            snapshot.payload["plan"]["steps"][0]["path"] = "/etc/passwd"  # type: ignore[index]

    def test_revocation_takes_effect(self):
        snapshot = _snapshot()
        self.approvals.grant(snapshot.action_id(), approver="nicol")
        self.approvals.revoke(snapshot.action_id())
        decision = resolve_escalation(self.engine.decide(snapshot), snapshot, self.approvals)
        self.assertEqual(decision.verdict, Verdict.ESCALATE)


class TestStructuredIntentRules(unittest.TestCase):
    """Rules key on parsed intent, so the classic string bypasses fail."""

    @staticmethod
    def _workspace_rule(snapshot: ActionSnapshot) -> RuleOutcome:
        for path in (snapshot.intent.resolved_paths if snapshot.intent else ()):
            if not path.startswith("/work/repo/"):
                return RuleOutcome(Verdict.DENY, "fs:outside_workspace",
                                   detail={"path": path})
        return RuleOutcome(Verdict.ALLOW, "fs:inside_workspace")

    def test_traversal_out_of_the_workspace_is_denied(self):
        engine = _engine(self._workspace_rule)
        snapshot = _snapshot(
            intent=parse_command(["cat", "../../etc/passwd"], cwd=Path("/work/repo")),
        )
        decision = engine.decide(snapshot)
        self.assertEqual(decision.verdict, Verdict.DENY)
        self.assertEqual(decision.detail["path"], "/etc/passwd")

    def test_in_workspace_write_is_allowed(self):
        engine = _engine(self._workspace_rule)
        snapshot = _snapshot(
            intent=parse_command(["cat", "src/main.py"], cwd=Path("/work/repo")),
        )
        self.assertEqual(engine.decide(snapshot).verdict, Verdict.ALLOW)

    def test_attached_and_separated_flag_spellings_decide_identically(self):
        engine = _engine(self._workspace_rule)
        for argv in (["curl", "-o", "/etc/cron.d/x", "u"],
                     ["curl", "--output=/etc/cron.d/x", "u"]):
            snapshot = _snapshot(intent=parse_command(argv, cwd=Path("/work/repo")))
            self.assertEqual(engine.decide(snapshot).verdict, Verdict.DENY, msg=argv)

    def test_same_argv_in_a_different_directory_is_a_different_decision(self):
        engine = _engine(self._workspace_rule)
        inside = _snapshot(intent=parse_command(["rm", "-rf", "build"],
                                                cwd=Path("/work/repo")))
        outside = _snapshot(intent=parse_command(["rm", "-rf", "build"],
                                                 cwd=Path("/production/live")))
        self.assertEqual(engine.decide(inside).verdict, Verdict.ALLOW)
        self.assertEqual(engine.decide(outside).verdict, Verdict.DENY)
        # ...and an approval for one can never cover the other.
        self.assertNotEqual(inside.action_id(), outside.action_id())


class TestEnforcementMatrix(unittest.TestCase):
    def test_undeclared_restriction_reports_ignored_not_safe(self):
        matrix = EnforcementMatrix()
        self.assertEqual(matrix.level_for("claude_cli", "network_egress"),
                         EnforcementLevel.IGNORED)

    def test_duplicate_claims_are_refused(self):
        matrix = EnforcementMatrix([
            EnforcementClaim("claude_cli", "workspace_scope", EnforcementLevel.SANDBOX_APPROX),
        ])
        with self.assertRaises(PolicyError):
            matrix.declare(
                EnforcementClaim("claude_cli", "workspace_scope", EnforcementLevel.HARD)
            )

    def test_undeclared_reports_the_coverage_gap(self):
        matrix = EnforcementMatrix([
            EnforcementClaim("claude_cli", "workspace_scope", EnforcementLevel.SANDBOX_APPROX),
        ])
        gaps = matrix.undeclared("claude_cli", ["workspace_scope", "network_egress"])
        self.assertEqual(gaps, ["network_egress"])

    def test_kernel_can_enumerate_what_is_not_a_real_boundary(self):
        matrix = EnforcementMatrix([
            EnforcementClaim("worktree", "shared_repo_isolation",
                             EnforcementLevel.SANDBOX_APPROX,
                             note="cwd scope only; absolute paths escape (ADR-0009)"),
            EnforcementClaim("file_lock", "single_writer", EnforcementLevel.HARD),
            EnforcementClaim("claude_cli", "network_egress", EnforcementLevel.PROMPT_ONLY),
        ])
        soft = {c.restriction for c in matrix.not_mechanically_enforced()}
        self.assertEqual(soft, {"shared_repo_isolation", "network_egress"})

    def test_verify_catches_a_claim_contradicted_by_evidence(self):
        # A label registry nobody falsifies is documentation with extra
        # steps (Codex review). A probe returns True when the restriction
        # CAN be escaped.
        matrix = EnforcementMatrix([
            EnforcementClaim("sandbox", "network_egress", EnforcementLevel.HARD),
            EnforcementClaim("sandbox", "fs_scope", EnforcementLevel.SANDBOX_APPROX),
        ])
        problems = matrix.verify({
            ("sandbox", "network_egress"): lambda: True,   # escaped anyway
            ("sandbox", "fs_scope"): lambda: True,         # expected for APPROX
        })
        self.assertEqual(len(problems), 1)
        self.assertIn("claimed HARD but the probe escaped it", problems[0])

    def test_verify_flags_probed_but_undeclared_restrictions(self):
        problems = EnforcementMatrix().verify({("sandbox", "fs_scope"): lambda: False})
        self.assertIn("probed but never declared", problems[0])

    def test_verify_reports_an_unrunnable_probe_instead_of_passing_it(self):
        def broken() -> bool:
            raise OSError("probe cannot run here")

        matrix = EnforcementMatrix([
            EnforcementClaim("sandbox", "fs_scope", EnforcementLevel.HARD),
        ])
        problems = matrix.verify({("sandbox", "fs_scope"): broken})
        self.assertIn("probe failed", problems[0])

    def test_real_worktree_isolation_probe_matches_its_claim(self):
        # The honest end of the honesty matrix: ADR-0009 claims worktree
        # isolation is a cwd SCOPE, not a hard boundary. Prove it — a
        # process whose cwd is the worktree can still write outside it via
        # an absolute path, which is exactly SANDBOX_APPROX, not HARD.
        import subprocess
        import sys
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inside = root / "worktree"
            inside.mkdir()
            outside = root / "shared" / "escaped.txt"
            outside.parent.mkdir()

            def escapes_cwd_scope() -> bool:
                subprocess.run(
                    [sys.executable, "-c",
                     f"open(r'{outside}', 'w').write('escaped')"],
                    cwd=inside, check=True, capture_output=True,
                )
                return outside.exists()

            problems = GNOSIS_ENFORCEMENT.verify({
                ("worktree", "shared_repo_isolation"): escapes_cwd_scope,
            })
            self.assertTrue(outside.exists())  # the escape really happened
            self.assertEqual(problems, [])     # ...and the claim admits it

    def test_gnosis_matrix_declares_every_restriction_the_kernel_relies_on(self):
        required = [
            "shared_repo_isolation", "orphaned_child_termination",
        ]
        self.assertEqual(GNOSIS_ENFORCEMENT.undeclared("worktree", required), [])
        soft = {(c.adapter, c.restriction)
                for c in GNOSIS_ENFORCEMENT.not_mechanically_enforced()}
        # Exactly the residuals the ADRs document; if a future change makes
        # one HARD, this test must be updated deliberately rather than the
        # claim drifting silently. The two `policy` entries are the ones
        # Codex's review of ADR-0013 forced into the open: a rule body is
        # unsandboxed operator code, and the launch gate is opt-in.
        self.assertEqual(soft, {("worktree", "shared_repo_isolation"),
                                ("worktree", "orphaned_child_termination"),
                                ("policy", "rule_purity"),
                                ("policy", "agent_launch_gate"),
                                ("convergence", "reviewer_read_only"),
                                ("convergence", "reviewer_independence"),
                                ("convergence", "verifier_execution"),
                                ("integration", "shared_branch_gate"),
                                ("integration", "semantic_correctness"),
                                ("integration", "rereview_provenance")})

    def test_gnosis_matrix_is_pinned_exactly(self):
        # Four mutants survived the previous suite: deleting a claim,
        # adding a fabricated one, or flipping a level all passed. The
        # matrix is only "machine-checked" if a change to it must be
        # deliberate (adversarial review).
        expected = {
            ("worktree", "shared_repo_isolation"): EnforcementLevel.SANDBOX_APPROX,
            ("worktree", "orphaned_child_termination"): EnforcementLevel.IGNORED,
            ("file_lock", "single_writer"): EnforcementLevel.HARD,
            ("replay", "no_network_in_strict_replay"): EnforcementLevel.HARD,
            ("claims", "no_stale_write_after_deposition"): EnforcementLevel.HARD,
            ("policy", "deny_by_default"): EnforcementLevel.HARD,
            ("convergence", "reviewer_read_only"): EnforcementLevel.SANDBOX_APPROX,
            ("integration", "verified_before_landing"): EnforcementLevel.HARD,
            ("integration", "rereview_provenance"): EnforcementLevel.IGNORED,
            ("integration", "semantic_correctness"): EnforcementLevel.IGNORED,
            ("integration", "shared_branch_gate"): EnforcementLevel.PROMPT_ONLY,
            ("convergence", "reviewer_independence"): EnforcementLevel.SANDBOX_APPROX,
            ("convergence", "verifier_execution"): EnforcementLevel.IGNORED,
            ("policy", "rule_purity"): EnforcementLevel.IGNORED,
            ("policy", "agent_launch_gate"): EnforcementLevel.PROMPT_ONLY,
        }
        actual = {(c.adapter, c.restriction): c.level
                  for c in GNOSIS_ENFORCEMENT.claims()}
        self.assertEqual(actual, expected)
        # Every claim cites the ADR that establishes it: an unexplained
        # security claim is not evidence.
        for claim in GNOSIS_ENFORCEMENT.claims():
            self.assertIn("ADR-", claim.note, msg=claim.restriction)

    def test_gnosis_matrix_records_the_honest_current_state(self):
        # The kernel's own claims, machine-checked: this is the table
        # least-privilege decisions consume, so it must match what the
        # ADRs actually say rather than what would sound better.
        matrix = EnforcementMatrix([
            EnforcementClaim(
                "worktree", "shared_repo_isolation", EnforcementLevel.SANDBOX_APPROX,
                note="cwd scope; an absolute path escapes it (ADR-0009 §1)",
            ),
            EnforcementClaim(
                "worktree", "orphaned_child_termination", EnforcementLevel.IGNORED,
                note="cooperative cancellation only; no job object (ADR-0009 residual)",
            ),
            EnforcementClaim(
                "file_lock", "single_writer", EnforcementLevel.HARD,
                note="OS advisory lock, cross-process (ADR-0004)",
            ),
            EnforcementClaim(
                "replay", "no_network_in_strict_replay", EnforcementLevel.HARD,
                note="live_fn is never invoked on a miss (ADR-0010)",
            ),
        ])
        self.assertEqual(
            matrix.level_for("worktree", "shared_repo_isolation"),
            EnforcementLevel.SANDBOX_APPROX,
        )
        self.assertEqual(
            matrix.level_for("worktree", "orphaned_child_termination"),
            EnforcementLevel.IGNORED,
        )
        self.assertEqual(len(matrix.not_mechanically_enforced()), 2)


if __name__ == "__main__":
    unittest.main()
