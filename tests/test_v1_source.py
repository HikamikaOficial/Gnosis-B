import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pytest
from v1_source import InstallSourceError, inspect_install_source

from tests import trust_fixtures as tf


@pytest.mark.parametrize("change", ["none", "commit", "tree", "dirty", "untracked", "subdirectory"])
def test_source_observation_binds_exact_clean_snapshot(tmp_path, change):
    repo = tf.git_repo(tmp_path / "repo")

    def git(*args):
        return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                              text=True, check=True).stdout.strip()

    commit, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
    if change == "commit":
        commit = "0" * 40
    elif change == "tree":
        tree = "0" * 40
    elif change == "dirty":
        (repo / "code.py").write_text("changed")
    elif change == "untracked":
        (repo / "unreviewed.py").write_text("changed")
    elif change == "subdirectory":
        repo = repo / "nested"
        repo.mkdir()
    if change == "none":
        observed = inspect_install_source(repo, expected_commit=commit, expected_tree=tree)
        assert (observed.repository, observed.commit, observed.tree) == (repo, commit, tree)
    else:
        with pytest.raises(InstallSourceError):
            inspect_install_source(repo, expected_commit=commit, expected_tree=tree)
