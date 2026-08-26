"""Prove the F-14 suite would catch the defects it claims to catch.

A green suite says nothing about whether its tests are load-bearing. The
only honest way to find out is to put each defect back and watch the
suite go red — and to record that it did, with exit codes, so the claim
is evidence rather than prose.

The defects put back here are the ones F-14 is about: identity that is
really just `git status`, a single fingerprint instead of two, a
before/after comparison that never compares, a broken probe that reads as
"nothing changed", a bundle written into the tree it is measuring, and a
summary that reports a pass for evidence the binding refused.

MF10..MF13 are the first independent review's finding: two equal
fingerprints prove two instants, not the interval between them. Each of
those four restores a version in which a check can change a file, read
the change and put the original bytes back without the capture noticing.

MF14..MF16 are the second review's: a write made through a memory-mapped
view need not generate any notification at all, so the covered inputs are
made unwritable instead of merely watched. These three take the
prevention away again.

MF17..MF20 are the third review's: which object is protected, whether it
is still the path it was opened by, when the identity was taken relative
to the locking window, and whether the volume demonstrably provides the
semantics all of this rests on.

MF21 is the fourth review's: the accepted domain must not be wider than
the demonstrated one.

MF22 is the fifth review's: a directory-like covered input — a submodule
gitlink is the realistic case — was reopened with a flag that makes a
directory openable, counted as a locked handle, and never identified. It
restores all three halves of that path at once, because removing any one
of them alone would not reproduce the defect.

MF23 and MF24 are the sixth review's: the lock protected the object and
not the path used to reach it, so a junction above a covered input could
be retargeted mid-run; and the classifier forgave any directory event
because the path was a directory again by the time it looked, which is
what a junction removed and recreated leaves behind.

MF25 is the seventh review's: `git ignores it` was authority for `it
cannot affect the result`, and an ignored file can be a real input.

MF26..MF29 are the eighth review's: covered, locked and identified by
object is not the same as byte-bound, and evidence that cannot be
re-derived from the files is not durable.

MF30..MF34 are the ninth review's: a path is not one stream. On NTFS a
file is `::$DATA` plus any number of named streams, each openable as
`path:name`, each readable by a check, and none of them visible to git
or to a handle on the main stream.

MF36..MF40 are the tenth review's: a named stream on a DIRECTORY can
appear and vanish inside the interval, leaving both inventories equal,
and only the observer's stream filters see the transient create.

    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/mutation_check_f14.py

Writes the transcript to stdout and, with `--out <path>`, to a file an
ADR can cite. Exits non-zero if any mutant survives, so it cannot produce
a clean transcript for an unguarded tree.

Kept separate from `scripts/mutation_check.py` on purpose: that script is
part of F-34's closed evidence and re-running it must keep producing the
same nine mutants over the same targeted suite.

The source files are restored in a `finally`, including on Ctrl-C. If
this process is killed outright, `git diff` shows exactly what to undo.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

CAPTURE = "src/gnosis/kernel/evidence_capture.py"
LOCK = "src/gnosis/kernel/input_lock.py"
SCRIPT = "scripts/capture_evidence.py"
OBSERVER = "src/gnosis/kernel/write_observer.py"
GITEV = "src/gnosis/kernel/git_evidence.py"

# Narrower than `tests/` on purpose: these are the tests that assert the
# binding, and a mutant that leaves them green has not been caught by
# anything a reader of F-14 would look at.
SUITE = [
    "tests/test_evidence_binding.py",
    "tests/test_git_evidence.py",
]


@dataclass(frozen=True)
class Mutant:
    """One defect, put back."""

    name: str
    description: str
    edits: list[tuple[str, str, str]] = field(default_factory=list)  # (file, old, new)


MUTANTS: list[Mutant] = [
    Mutant(
        "MF1", "the tree's identity is `git status --porcelain` again — a "
               "state and a name, never a content",
        [(CAPTURE,
          """    try:
        payload = dict(fingerprint(repo))
    except OSError as exc:""",
          """    try:
        payload = {"is_repo": True, "status": subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo, capture_output=True,
            text=True, check=False).stdout}
    except OSError as exc:""")],
    ),
    Mutant(
        "MF2", "the before/after comparison is removed: two different "
               "fingerprints bind anyway",
        [(CAPTURE,
          """    if pre.digest != post.digest:
        return TreeBinding(pre, post, BindingVerdict.TREE_MUTATED,
                           describe_drift(pre.fingerprint, post.fingerprint))""",
          """    if False:
        return TreeBinding(pre, post, BindingVerdict.TREE_MUTATED, ())""")],
    ),
    Mutant(
        "MF3", "an unavailable identity binds: a probe that could not "
               "answer reads as agreement",
        [(CAPTURE,
          """    if not pre.available or not post.available or pre.digest is None or post.digest is None:
        return TreeBinding(pre, post, BindingVerdict.IDENTITY_UNAVAILABLE)""",
          """    if False:
        return TreeBinding(pre, post, BindingVerdict.IDENTITY_UNAVAILABLE)""")],
    ),
    Mutant(
        "MF4", "the post fingerprint is never taken, so the capture has "
               "only one end to compare",
        [(CAPTURE,
          """            finally:
                lock.release()
            post = identity(repo)""",
          """            finally:
                lock.release()
            pass""")],
    ),
    Mutant(
        "MF5", "the bundle is staged inside the repository again, so the "
               "evidence appears in its own post fingerprint",
        [(SCRIPT,
          '    return Path(tempfile.mkdtemp(prefix="gnosis-evidence-"))',
          '    return Path(tempfile.mkdtemp(prefix="gnosis-evidence-", '
          'dir=str(REPO / ".gnosis")))')],
    ),
    Mutant(
        "MF6", "an untracked file whose bytes could not be read is still "
               "called an identified tree",
        [(CAPTURE,
          """    if unreadable:
        return TreeIdentity(False, None, payload,
                            "untracked files could not be read: " + ", ".join(unreadable))""",
          """    if False:
        return TreeIdentity(False, None, payload, "")""")],
    ),
    Mutant(
        "MF7", "a failed git probe is accepted as an identity",
        [(CAPTURE,
          """    if "probe_failed" in payload:
        return TreeIdentity(False, None, payload,
                            f"git probe failed: {payload['probe_failed']}")""",
          """    if False:
        return TreeIdentity(False, None, payload, "")""")],
    ),
    Mutant(
        "MF8", "the summary reports a pass for evidence the binding "
               "refused (ADR-0025 round 2, transplanted onto this surface)",
        [(CAPTURE,
          """        "all_passed": valid and checks_verdict is ChecksVerdict.ALL_CLEAN,
        "gates_clean": valid and checks_verdict in (
            ChecksVerdict.ALL_CLEAN, ChecksVerdict.WITHIN_BASELINE),""",
          """        "all_passed": checks_verdict is ChecksVerdict.ALL_CLEAN,
        "gates_clean": checks_verdict in (
            ChecksVerdict.ALL_CLEAN, ChecksVerdict.WITHIN_BASELINE),""")],
    ),
    Mutant(
        "MF9", "a capture with no checks is allowed to report a result",
        [(CAPTURE,
          "    if not commands:\n        raise EmptyCaptureError(",
          "    if commands and not commands:\n        raise EmptyCaptureError(")],
    ),
    # MF10..MF13 are the first independent review's finding: two equal
    # fingerprints do not prove the interval between them. Each of these
    # restores a version in which a change that undoes itself passes.
    Mutant(
        "MF10", "an observed write to a covered input is not a violation, "
                "so a change that undoes itself passes",
        [(CAPTURE,
          """    verdict = (ObservationVerdict.INPUTS_MUTATED if violations
               else ObservationVerdict.CLEAN)""",
          "    verdict = ObservationVerdict.CLEAN")],
    ),
    Mutant(
        "MF11", "an observation that could have missed something is "
                "accepted as if it had seen nothing",
        [(CAPTURE,
          """    if not observation.available or not observation.complete:
        return Boundary(
            ObservationVerdict.UNOBSERVED, observation.mechanism,""",
          """    if False:
        return Boundary(
            ObservationVerdict.UNOBSERVED, observation.mechanism,""")],
    ),
    Mutant(
        "MF12", "validity goes back to the binding alone: equal endpoints "
                "are enough again (the reviewed defect, restored)",
        [(CAPTURE,
          """        return (self.binding.verdict is BindingVerdict.BOUND
                and self.boundary.verdict is ObservationVerdict.CLEAN)""",
          "        return self.binding.verdict is BindingVerdict.BOUND")],
    ),
    Mutant(
        "MF13", "a path that appears and disappears inside the run is not "
                "judged, so create-read-delete is invisible again",
        [(CAPTURE,
          """    for path, action in sorted(unknown.items()):
        # No `git check-ignore` here, and that is the seventh review's
        # repair. A path nobody declared is an unknown, and an unknown is
        # a violation: being ignored by git was never evidence that a
        # check cannot read it.
        violations.append(f"{action}: {path}")""",
          "    allowed_count += len(unknown)")],
    ),
    # MF14..MF16 are the SECOND independent review's finding: a write made
    # through a memory-mapped view need not notify anything, so watching
    # cannot be the whole boundary. Each of these removes the prevention
    # that closes it and leaves only the watching.
    Mutant(
        "MF14", "the covered inputs are never made unwritable; only the "
                "write stream is left, which a mapped write can evade",
        [(CAPTURE,
          """            lock = input_lock(repo)
            directories = stream_directories(repo, allowed_writes)
            lock_outcome = lock.acquire(sorted(covered), directories)""",
          """            lock = input_lock(repo)
            lock_outcome = LockOutcome(True, 0, (), "none")""")],
    ),
    Mutant(
        "MF15", "a lock that could not be enforced is recorded as if it "
                "had been",
        [(CAPTURE,
          "    if lock is not None and not lock.enforced:",
          "    if False:")],
    ),
    Mutant(
        "MF16", "the checks run even when the inputs could not be "
                "protected",
        [(CAPTURE,
          "                if lock_outcome.enforced:",
          "                if True:")],
    ),
    # MF17..MF20 are the THIRD independent review's questions: which
    # object is protected, when it was identified, and on what volume the
    # guarantee has actually been demonstrated.
    Mutant(
        "MF17", "a reparse point among the covered inputs is locked like "
                "any other file, so the lock and the check can follow "
                "different redirections",
        [(LOCK,
          """                if (attributes != _INVALID_FILE_ATTRIBUTES
                        and attributes & _FILE_ATTRIBUTE_REPARSE_POINT):""",
          "                if False:")],
    ),
    Mutant(
        "MF18", "the protected handles are never identified, so nothing "
                "says which object was locked",
        [(LOCK,
          """                problem = self._identify(relative, target, handle, identities)
                if problem is not None:
                    refused.append(problem)""",
          '                identities[relative] = ""')],
    ),
    Mutant(
        "MF19", "any volume is assumed to provide the semantics the "
                "boundary needs",
        [(LOCK,
          """            volume = probe(self.root)
            if not volume.supported:""",
          """            volume = probe(self.root)
            if False:""")],
    ),
    Mutant(
        "MF20", "the identity is not re-taken once the inputs are "
                "unwritable, so it describes a tree from before the "
                "locking window",
        [(CAPTURE,
          """                    prepared = identity(repo)
                    drift = _preparation_drift(pre, prepared)""",
          """                    prepared = pre
                    drift = ()""")],
    ),
    # MF21 is the FOURTH independent review's finding: the accepted domain
    # was wider than the demonstrated one. The mutant is the old line.
    Mutant(
        "MF21", "ReFS goes back into the demonstrated domain, so a "
                "filesystem the boundary has never run on is accepted",
        [(LOCK,
          '    _SUPPORTED_FILESYSTEMS = frozenset({"NTFS"})',
          '    _SUPPORTED_FILESYSTEMS = frozenset({"NTFS", "ReFS"})')],
    ),
    # MF22 is the FIFTH independent review's finding, verbatim: a
    # directory-like covered input reopened with FILE_FLAG_BACKUP_SEMANTICS,
    # appended to the handle list, and never identified.
    Mutant(
        "MF22", "a directory-like covered input is reopened with "
                "FILE_FLAG_BACKUP_SEMANTICS and counted as locked without "
                "ever being identified",
        [(LOCK,
          """                if (attributes != _INVALID_FILE_ATTRIBUTES
                        and attributes & _FILE_ATTRIBUTE_DIRECTORY):""",
          """                if False:"""),
         (LOCK,
          """                    refused.append(f"{relative} (error {error})")
                    continue""",
          """                    if error == 5:
                        handle = _kernel32.CreateFileW(
                            str(target), _GENERIC_READ, _FILE_SHARE_READ, None,
                            _OPEN_EXISTING, _FILE_FLAG_BACKUP_SEMANTICS, None)
                        if handle and handle != _INVALID_HANDLE_VALUE:
                            self._handles.append(handle)
                            continue
                    refused.append(f"{relative} (error {error})")
                    continue"""),
         (LOCK,
          """            unidentified = (len(self._handles) - held_before) - len(identities)
            if unidentified > 0:""",
          """            unidentified = 0
            if False:""")],
    ),
    # MF23 and MF24 are the SIXTH review's two halves: the lock held the
    # object and not the name, and the classifier forgave a directory
    # that was a directory again by the time it looked.
    Mutant(
        "MF23", "an ancestor junction is accepted again, so the path used "
                "to reach a covered input can be retargeted while the "
                "object stays locked",
        [(LOCK,
          """                redirect = self._redirectable_ancestor(relative, ancestors)
                if redirect is not None:
                    refused.append(redirect)
                    continue""",
          """                redirect = None"""),
         (LOCK,
          """            root_redirect = reparse_in_chain(self.root)
            if root_redirect is not None:""",
          """            root_redirect = None
            if False:""")],
    ),
    Mutant(
        "MF24", "a directory event is forgiven for being a directory, so "
                "remove-and-recreate of a structural component passes",
        [(CAPTURE,
          '        elif event.action == "modified" and (repo / path).is_dir():',
          "        elif (repo / path).is_dir():")],
    ),
    # MF25 is the SEVENTH review's: `git ignores it` used as authority for
    # `it cannot affect the result`. It takes the ignored files back out of
    # the input domain AND restores the check-ignore allowance, because
    # either one alone leaves the other half of the repair standing.
    Mutant(
        "MF25", "git-ignored paths leave the input domain and are "
                "forgiven again when they change",
        [(CAPTURE,
          """    for entry in _git_lines(
            repo, ["ls-files", "-z", "--others", "--ignored", "--exclude-standard"]):""",
          "    for entry in []:"),
         (CAPTURE,
          """    for path, action in sorted(unknown.items()):
        # No `git check-ignore` here, and that is the seventh review's
        # repair. A path nobody declared is an unknown, and an unknown is
        # a violation: being ignored by git was never evidence that a
        # check cannot read it.
        violations.append(f"{action}: {path}")""",
          """    import subprocess as _sp
    _proc = _sp.run(["git", "check-ignore", "-z", "--stdin"], cwd=repo,
                    input="\\0".join(sorted(unknown)) + "\\0",
                    capture_output=True, text=True, check=False)
    _ignored = {p for p in _proc.stdout.split("\\0") if p}
    for path, action in sorted(unknown.items()):
        if path in _ignored:
            allowed_count += 1
        else:
            violations.append(f"{action}: {path}")""")],
    ),
    # MF26..MF29 are the EIGHTH review's: a file id says which object and
    # a lock says it did not move, and neither states the bytes.
    Mutant(
        "MF26", "inputs are identified by file id but never hashed, so "
                "the evidence cannot state what was in them",
        [(LOCK,
          """            digest = handle_digest(handle)
            if digest is None:
                return f"{relative} (bytes could not be read for hashing)"
            identities[relative] = f"{serial:016x}:{file_id}"
            self._digests[relative] = digest""",
          '            identities[relative] = f"{serial:016x}:{file_id}"\n'
          '            self._digests[relative] = ""')],
    ),
    Mutant(
        "MF27", "an ignored nested clone is dropped from the input domain "
                "instead of expanded, so its bytes leave the boundary",
        [(CAPTURE,
          """        for found in (repo / candidate).rglob("*"):
            if found.is_file():
                ignored.append(found.relative_to(repo).as_posix())""",
          "        continue")],
    ),
    Mutant(
        "MF28", "content already sitting under an OUTPUT root is not "
                "hashed, so a planted file can be read as an unnamed input",
        [(CAPTURE,
          """                    write_manifest(staging, lock_outcome.content_digests,
                                   file_digests(repo, output_paths(repo, allowed_writes)))""",
          "                    write_manifest(staging, lock_outcome.content_digests, {})")],
    ),
    Mutant(
        "MF29", "the consumer stops checking that every locked input was "
                "hashed",
        [(CAPTURE,
          "    if lock is not None and not lock.fully_bound:",
          "    if False:")],
    ),
    # MF30..MF34 are the NINTH review's: a path is not one stream, and
    # everything below was measured before it was written.
    Mutant(
        "MF30", "named data streams are not enumerated, locked or hashed, so "
                "an ADS reaches a check with no digest naming its bytes",
        [(LOCK,
          "            inventory, stream_failures = stream_inventory(\n"
          "                self.root, sorted(paths), directories)",
          "            inventory, stream_failures = {}, ()")],
    ),
    Mutant(
        "MF31", "a stream enumeration that FAILED is treated as a path with "
                "no streams, which is the silent-ignore the review forbade",
        [(LOCK,
          """        if found is None:
            failures.append(f"{relative or '.'} (named data streams could not be "
                            "enumerated, so its bytes cannot be stated)")
            continue""",
          """        if found is None:
            continue""")],
    ),
    Mutant(
        "MF32", "the inventory comparison is dropped, so a stream created "
                "inside the protected interval is invisible again",
        [(CAPTURE, "    if streams:", "    if False:")],
    ),
    Mutant(
        "MF33", "only files are in the stream domain, so a directory's "
                "streams -- which git never enumerates -- go unbound",
        [(LOCK,
          """        parts = clean.split("/")[:-1]
        for index in range(len(parts)):
            domain.add("/".join(parts[:index + 1]))""",
          "        continue")],
    ),
    Mutant(
        "MF34", "streams of a pre-existing OUTPUT file are not hashed, so an "
                "ADS under an output root is an unnamed prior input",
        [(CAPTURE,
          """    found = named_streams(target)
    if found is None:
        return ("<streams could not be enumerated>",)
    return tuple(name for name, _ in found)""",
          "    return ()")],
    ),
    Mutant(
        "MF35", "the disk is not walked, so a directory holding no input at "
                "all keeps its streams outside the boundary",
        [(CAPTURE,
          """            directories = stream_directories(repo, allowed_writes)""",
          "            directories = ()")],
    ),
    # MF36..MF40 are the TENTH review's: a named stream that appears and
    # disappears on a DIRECTORY inside the interval, which the endpoints and
    # the inventory both miss and the observer catches only with the stream
    # filters.
    Mutant(
        "MF36", "the observer stops requesting the stream filters, so a "
                "directory-stream create is invisible again",
        [(OBSERVER,
          """    _NOTIFY_ALL = (0x001 | 0x002 | 0x004 | 0x008 | 0x010 | 0x040 | 0x100
                   | _NOTIFY_STREAM)""",
          "    _NOTIFY_ALL = (0x001 | 0x002 | 0x004 | 0x008 | 0x010 | 0x040 "
          "| 0x100)")],
    ),
    Mutant(
        "MF37", "the parent watch stops recording the root's own stream "
                "events, so a stream on the repository root escapes",
        [(OBSERVER,
          """                    keep.append(WriteEvent(label, f":{stream}"))""",
          "                    pass")],
    ),
    Mutant(
        "MF38", "the classifier forgives every stream action, so an "
                "added_stream is no longer a violation",
        [(CAPTURE,
          'event.action not in ("added_stream", "removed_stream")',
          "True")],
    ),
    Mutant(
        "MF39", "the classifier judges modified_stream too, so reading a "
                "locked stream to hash it is falsely a violation",
        [(CAPTURE,
          '("added_stream", "removed_stream")',
          '("added_stream", "removed_stream", "modified_stream")')],
    ),
    Mutant(
        "MF40", "the observer ignores the root watch's incompleteness, so a "
                "root whose streams could not be watched reads as clean",
        [(OBSERVER,
          "            if not root.complete:",
          "            if False:")],
    ),
    # MF41..MF42 are the ELEVENTH review's: the CLEAN-over-COMPLETE audit.
    Mutant(
        "MF41", "the lock shares WRITE, so a pre-existing writable mapping no "
                "longer blocks it and a mapped write can end CLEAN",
        [(LOCK,
          "                    str(target), _GENERIC_READ, _FILE_SHARE_READ, None,",
          "                    str(target), _GENERIC_READ, _FILE_SHARE_READ | 0x2, "
          "None,")],
    ),
    Mutant(
        "MF42", "the parent watch stops filtering to the root entry, so a "
                "stream on a sibling of the repository reads as a violation",
        [(OBSERVER,
          "                    if owner != self.entry or not stream:",
          "                    if not stream:")],
    ),
    # MF43..MF47 are F-17's: the evidence bundle is now tamper-evident, and
    # a hook or config written under .git during the capture is judged.
    Mutant(
        "MF43", "the bundle manifest is never written, so the evidence has no "
                "hash chain and a post-capture edit goes unnoticed",
        [(CAPTURE,
          "    write_bundle_manifest(staging)",
          "    pass  # write_bundle_manifest(staging)")],
    ),
    Mutant(
        "MF44", "verify_bundle stops comparing hashes, so a changed bundle "
                "file still verifies",
        [(CAPTURE,
          "        if actual != recorded[rel]:",
          "        if False:")],
    ),
    Mutant(
        "MF45", "a hook or config written under .git is no longer judged, so "
                "installing a hook during the capture reads as CLEAN",
        [(CAPTURE,
          "    owner = path.split(\":\", 1)[0]\n"
          "    if owner.startswith(_GIT_HOOKS) and not owner.endswith(_HOOK_SAMPLE):\n"
          "        return True\n"
          "    return owner == _GIT_CONFIG",
          "    return False")],
    ),
    Mutant(
        "MF46", "the .sample exclusion is dropped, so writing an inert sample "
                "hook is falsely a machinery tamper",
        [(CAPTURE,
          "    if owner.startswith(_GIT_HOOKS) and not owner.endswith(_HOOK_SAMPLE):",
          "    if owner.startswith(_GIT_HOOKS):")],
    ),
    Mutant(
        "MF47", "the machinery-tamper verdict is dropped, so a judged hook "
                "write is collected and then ignored",
        [(CAPTURE,
          "    if machinery_violations:",
          "    if False:")],
    ),
    # MF48..MF50 are F-17's blockers: a worktree/submodule capture must fail
    # closed (its git machinery is outside the watched tree), and the bundle's
    # tamper-evidence rests on an external anchor, not the in-bundle digest.
    Mutant(
        "MF48", "the classifier ignores an ineligible git topology, so a "
                "worktree capture no longer fails closed",
        [(CAPTURE,
          "    if topology_reason is not None:",
          "    if False and topology_reason is not None:")],
    ),
    Mutant(
        "MF49", "run_capture runs the checks even on an ineligible topology, "
                "so a worktree capture executes with its machinery unobserved",
        [(CAPTURE,
          "        if pre.available and topology_ok and resolution_ok:",
          "        if pre.available and resolution_ok:")],
    ),
    Mutant(
        "MF50", "verify_bundle ignores the external anchor, so a recomputed "
                "manifest passes as if it were the trusted bundle",
        [(CAPTURE,
          "    if expected_digest is not None and recomputed != expected_digest:",
          "    if False:")],
    ),
    # MF51..MF56 are the THIRD F-17 review's BLOCKER A: git's object / ref /
    # ancestry RESOLUTION can be redirected without touching the objects'
    # bytes — a refs/replace ref (loose, packed, or a raw packed-refs edit)
    # makes `git diff HEAD` report against a substituted tree, and the binding
    # honours it. A redirection active at capture start fails closed
    # (MACHINERY_REDIRECTED); a write to a redirect surface during the interval
    # is judged (MACHINERY_MUTATED). These put each half of that back.
    Mutant(
        "MF51", "the resolution-redirect predicate returns False, so "
                "refs/replace, alternates, grafts, shallow and packed-refs "
                "writes go back to counted-not-judged",
        [(CAPTURE,
          "    owner = path.split(\":\", 1)[0]\n"
          "    if owner.startswith(_GIT_REFS_REPLACE):\n"
          "        return True\n"
          "    return owner in _GIT_REDIRECT_SURFACES",
          "    return False")],
    ),
    Mutant(
        "MF52", "run_capture ignores the resolution gate, so a capture over a "
                "repository with an active replace ref runs its checks anyway",
        [(CAPTURE,
          "        if pre.available and topology_ok and resolution_ok:",
          "        if pre.available and topology_ok:")],
    ),
    Mutant(
        "MF53", "the classifier drops the MACHINERY_REDIRECTED branch, so an "
                "active redirection no longer fails closed",
        [(CAPTURE,
          "    if resolution_reason is not None:",
          "    if False and resolution_reason is not None:")],
    ),
    Mutant(
        "MF54", "git_resolution_faithful stops looking for replace refs, so a "
                "replace ref active at capture start is not refused",
        [(GITEV,
          "        repo_path, [\"for-each-ref\", \"--format=%(refname)\", \"refs/replace\"])\n"
          "    if code == 0 and out.strip():",
          "        repo_path, [\"for-each-ref\", \"--format=%(refname)\", \"refs/replace\"])\n"
          "    if False and code == 0 and out.strip():")],
    ),
    Mutant(
        "MF55", "git_resolution_faithful stops checking the alternates / grafts "
                "redirection files, so an external object store is accepted",
        [(GITEV,
          "    for rel, why in redirections.items():",
          "    for rel, why in {}.items():")],
    ),
    Mutant(
        "MF56", "the interval classifier stops routing resolution redirects to "
                "the judged set, so an ABA replace or packed-refs edit passes",
        [(CAPTURE,
          "        if _is_git_machinery_tamper(path) or _is_git_resolution_redirect(path):",
          "        if _is_git_machinery_tamper(path):")],
    ),
]


def _pytest(paths: list[str], fail_fast: bool) -> tuple[int, str]:
    argv = [sys.executable, "-m", "pytest", *paths, "-q"]
    if fail_fast:
        argv.append("-x")
    proc = subprocess.run(argv, cwd=REPO, capture_output=True, text=True, check=False)
    tail = (proc.stdout.strip().splitlines() or [""])[-1][:200]
    return proc.returncode, tail


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    lines: list[str] = []

    def say(text: str = "") -> None:
        print(text, flush=True)
        lines.append(text)

    say("MUTATION CHECK — F-14, evidence binds bytes over a protected, observed interval")
    say("=" * 72)
    say(f"targeted suite: {' '.join(SUITE)}")
    say()

    originals = {rel: (REPO / rel).read_text(encoding="utf-8")
                 for rel in {edit[0] for m in MUTANTS for edit in m.edits}}

    code, tail = _pytest(SUITE, fail_fast=False)
    say(f"BASELINE (repair in place): exit={code}  {tail}")
    if code != 0:
        say()
        say("ABORTED: the baseline suite is not green, so nothing a mutant "
            "does could be attributed to the mutant.")
        if args.out:
            args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 1
    say()

    survived: list[str] = []
    try:
        for mutant in MUTANTS:
            for rel, old, new in mutant.edits:
                source = (REPO / rel).read_text(encoding="utf-8")
                if old not in source:
                    survived.append(f"{mutant.name} (NOT APPLIED)")
                    say(f"{mutant.name}: {mutant.description}")
                    say(f"  ABORTED: the target text is no longer present in {rel}.")
                    say("  verdict: NOT APPLIED — this mutant proves nothing.")
                    say()
                    break
                (REPO / rel).write_text(source.replace(old, new, 1), encoding="utf-8")
            else:
                code, tail = _pytest(SUITE, fail_fast=True)
                say(f"{mutant.name}: {mutant.description}")
                say(f"  files:  {', '.join(sorted({e[0] for e in mutant.edits}))}")
                say(f"  result: exit={code}  {tail}")
                say(f"  verdict: {'CAUGHT' if code != 0 else 'SURVIVED'}")
                say()
                if code == 0:
                    survived.append(mutant.name)
            # Restored between mutants as well as at the end: one mutant
            # must never be measured against another's edit.
            for rel, text in originals.items():
                (REPO / rel).write_text(text, encoding="utf-8")
    finally:
        for rel, text in originals.items():
            (REPO / rel).write_text(text, encoding="utf-8")

    code, tail = _pytest(SUITE, fail_fast=False)
    say(f"RESTORED: exit={code}  {tail}")
    say()
    say(f"mutants: {len(MUTANTS)}  survived/aborted: {len(survived)}"
        + (f"  -> {', '.join(survived)}" if survived else ""))

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return 1 if survived or code != 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
