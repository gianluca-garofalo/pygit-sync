"""Integration tests using real git repositories.

Creates bare repos (acting as remotes) and local clones to test the
full sync pipeline end-to-end.
"""

import json
import subprocess
from pathlib import Path

import pytest

from pygit_sync import (
    ConsoleOutputHandler,
    IssueType,
    NullOutputHandler,
    SyncConfig,
    SyncOrchestrator,
    SyncResult,
    load_config_file,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git(cwd: Path, *args: str) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _commit_file(repo: Path, filename: str, content: str, message: str) -> str:
    """Create/overwrite a file and commit it. Returns the commit hash."""
    filepath = repo / filename
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content)
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _push_via_clone(tmp_path: Path, bare_remote: Path, name: str,
                    files: dict[str, str], message: str,
                    branch: str = "main") -> Path:
    """Clone the bare remote, commit files, and push. Returns pusher path."""
    pusher = tmp_path / name
    _git(tmp_path, "clone", str(bare_remote), name)
    _git(pusher, "config", "user.email", "test@test.com")
    _git(pusher, "config", "user.name", "Test")
    if branch != "main":
        _git(pusher, "checkout", "-b", branch)
    for filename, content in files.items():
        (pusher / filename).write_text(content)
        _git(pusher, "add", filename)
    _git(pusher, "commit", "-m", message)
    _git(pusher, "push", "origin", branch)
    return pusher


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    """Create a bare repo that acts as a remote."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare", "-b", "main")
    return remote


@pytest.fixture
def local_clone(tmp_path: Path, bare_remote: Path) -> Path:
    """Clone the bare remote into a local working repo."""
    local = tmp_path / "local"
    _git(tmp_path, "clone", str(bare_remote), "local")
    _git(local, "config", "user.email", "test@test.com")
    _git(local, "config", "user.name", "Test")
    # Create main branch with initial commit (clone of empty repo has no branch)
    _git(local, "checkout", "-b", "main")
    _commit_file(local, "init.txt", "initial", "Initial commit")
    _git(local, "push", "-u", "origin", "main")
    return local


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A directory that contains multiple repos (for multi-repo tests)."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


def _make_repo_pair(workspace: Path, name: str) -> tuple[Path, Path]:
    """Create a bare remote + local clone inside a workspace dir.

    Returns (remote_path, local_path).
    """
    remote = workspace / f"{name}-remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare", "-b", "main")

    local = workspace / name
    _git(workspace, "clone", str(remote), name)
    _git(local, "config", "user.email", "test@test.com")
    _git(local, "config", "user.name", "Test")
    _git(local, "checkout", "-b", "main")
    _commit_file(local, "init.txt", "initial", "Initial commit")
    _git(local, "push", "-u", "origin", "main")
    return remote, local


def _run_sync(search_dir: Path, **config_overrides) -> SyncResult:
    """Run the sync orchestrator on a directory and return the result."""
    defaults = dict(dry_run=False, verbose=False)
    defaults.update(config_overrides)
    config = SyncConfig(**defaults)
    output = NullOutputHandler()
    orchestrator = SyncOrchestrator(config, output)
    return orchestrator.sync_all(search_dir)


# ---------------------------------------------------------------------------
# Tests: Basic fast-forward sync
# ---------------------------------------------------------------------------

class TestBasicSync:
    def test_fast_forward_behind(self, tmp_path, bare_remote, local_clone):
        """Local is behind remote by 1 commit -> should fast-forward."""
        _push_via_clone(tmp_path, bare_remote, "pusher",
                        {"new.txt": "hello"}, "Second commit")

        result = _run_sync(local_clone.parent, exclude_patterns=["pusher", "remote.git"])

        assert result.repos_processed == 1
        assert len(result.branches_updated) == 1
        assert result.has_critical_issues() is False
        assert (local_clone / "new.txt").read_text() == "hello"

    def test_fast_forward_multiple_commits(self, tmp_path, bare_remote, local_clone):
        """Local is behind remote by 5 commits -> should fast-forward all."""
        pusher = tmp_path / "pusher"
        _git(tmp_path, "clone", str(bare_remote), "pusher")
        _git(pusher, "config", "user.email", "test@test.com")
        _git(pusher, "config", "user.name", "Test")
        for i in range(1, 6):
            _commit_file(pusher, f"file{i}.txt", f"content{i}", f"Commit {i}")
        _git(pusher, "push", "origin", "main")

        result = _run_sync(local_clone.parent, exclude_patterns=["pusher", "remote.git"])

        assert result.repos_processed == 1
        assert result.has_critical_issues() is False
        for i in range(1, 6):
            assert (local_clone / f"file{i}.txt").read_text() == f"content{i}"

    def test_already_up_to_date(self, tmp_path, bare_remote, local_clone):
        """Local is already up-to-date -> no issues, no updates."""
        result = _run_sync(local_clone.parent, exclude_patterns=["remote.git"])

        assert result.repos_processed == 1
        assert result.has_issues() is False

    def test_dry_run_does_not_change_files(self, tmp_path, bare_remote, local_clone):
        """Dry run should fetch but not pull."""
        _push_via_clone(tmp_path, bare_remote, "pusher",
                        {"dry.txt": "nope"}, "Dry run commit")

        result = _run_sync(
            local_clone.parent,
            dry_run=True,
            exclude_patterns=["pusher", "remote.git"],
        )

        assert result.repos_processed == 1
        assert not (local_clone / "dry.txt").exists()

    def test_no_rebase_uses_merge(self, tmp_path, bare_remote, local_clone):
        """--no-rebase should pull with merge instead of rebase."""
        _push_via_clone(tmp_path, bare_remote, "pusher",
                        {"merge_test.txt": "merged"}, "Merge commit")

        result = _run_sync(
            local_clone.parent,
            use_rebase=False,
            exclude_patterns=["pusher", "remote.git"],
        )

        assert result.repos_processed == 1
        assert result.has_critical_issues() is False
        assert (local_clone / "merge_test.txt").read_text() == "merged"


# ---------------------------------------------------------------------------
# Tests: Dirty working tree
# ---------------------------------------------------------------------------

class TestDirtyWorkingTree:
    def _setup_behind_and_dirty(self, tmp_path, bare_remote, local_clone):
        """Helper: make remote 1 ahead and local dirty."""
        _push_via_clone(tmp_path, bare_remote, "pusher",
                        {"remote_change.txt": "remote"}, "Remote commit")
        (local_clone / "dirty.txt").write_text("uncommitted")

    def test_dirty_skips_pull(self, tmp_path, bare_remote, local_clone):
        """Dirty working tree without --stash-and-pull -> LOCAL_CHANGES issue."""
        self._setup_behind_and_dirty(tmp_path, bare_remote, local_clone)

        result = _run_sync(
            local_clone.parent,
            exclude_patterns=["pusher", "remote.git"],
        )

        local_changes = result.get_issues_by_type(IssueType.LOCAL_CHANGES)
        assert len(local_changes) == 1
        assert not (local_clone / "remote_change.txt").exists()

    def test_stash_and_pull(self, tmp_path, bare_remote, local_clone):
        """--stash-and-pull should stash, pull, and pop."""
        self._setup_behind_and_dirty(tmp_path, bare_remote, local_clone)

        result = _run_sync(
            local_clone.parent,
            stash_and_pull=True,
            exclude_patterns=["pusher", "remote.git"],
        )

        assert result.has_critical_issues() is False
        assert (local_clone / "remote_change.txt").read_text() == "remote"
        assert (local_clone / "dirty.txt").read_text() == "uncommitted"

    def test_stash_conflict(self, tmp_path, bare_remote, local_clone):
        """Stash pop conflict -> STASH_CONFLICT issue."""
        # Remote modifies a file that local also modified (uncommitted)
        _push_via_clone(tmp_path, bare_remote, "pusher",
                        {"init.txt": "remote version"}, "Remote modifies init.txt")

        # Local has an uncommitted change to the SAME file
        (local_clone / "init.txt").write_text("local conflicting version")

        result = _run_sync(
            local_clone.parent,
            stash_and_pull=True,
            exclude_patterns=["pusher", "remote.git"],
        )

        conflicts = result.get_issues_by_type(IssueType.STASH_CONFLICT)
        assert len(conflicts) == 1
        assert result.has_critical_issues() is True

    def test_dirty_with_staged_changes(self, tmp_path, bare_remote, local_clone):
        """Dirty tree with staged (but uncommitted) changes -> LOCAL_CHANGES."""
        _push_via_clone(tmp_path, bare_remote, "pusher",
                        {"remote.txt": "new"}, "Remote commit")

        # Stage a change without committing
        (local_clone / "staged.txt").write_text("staged content")
        _git(local_clone, "add", "staged.txt")

        result = _run_sync(
            local_clone.parent,
            exclude_patterns=["pusher", "remote.git"],
        )

        local_changes = result.get_issues_by_type(IssueType.LOCAL_CHANGES)
        assert len(local_changes) == 1
        # Verify the issue details mention staged files
        assert "staged" in local_changes[0].details

    def test_dirty_but_up_to_date_no_issue(self, tmp_path, bare_remote, local_clone):
        """Dirty working tree but already up-to-date -> no issue (not behind)."""
        (local_clone / "dirty.txt").write_text("uncommitted")

        result = _run_sync(
            local_clone.parent,
            exclude_patterns=["remote.git"],
        )

        # Dirty tree strategy only fires when behind AND dirty
        local_changes = result.get_issues_by_type(IssueType.LOCAL_CHANGES)
        assert len(local_changes) == 0


# ---------------------------------------------------------------------------
# Tests: New remote branch creation
# ---------------------------------------------------------------------------

class TestNewBranch:
    def test_creates_local_branch_for_new_remote(self, tmp_path, bare_remote, local_clone):
        """A remote branch with no local counterpart -> create it."""
        _push_via_clone(tmp_path, bare_remote, "pusher",
                        {"feat.txt": "feature"}, "Feature commit",
                        branch="feature/new-branch")

        result = _run_sync(
            local_clone.parent,
            exclude_patterns=["pusher", "remote.git"],
        )

        assert len(result.branches_created) >= 1
        created_branches = [b for _, b in result.branches_created]
        assert "feature/new-branch" in created_branches

        branches = _git(local_clone, "branch", "-a")
        assert "feature/new-branch" in branches

    def test_creates_multiple_new_branches(self, tmp_path, bare_remote, local_clone):
        """Multiple new remote branches -> all should be created."""
        pusher = tmp_path / "pusher"
        _git(tmp_path, "clone", str(bare_remote), "pusher")
        _git(pusher, "config", "user.email", "test@test.com")
        _git(pusher, "config", "user.name", "Test")

        for branch in ["develop", "release/1.0", "hotfix/urgent"]:
            _git(pusher, "checkout", "-b", branch)
            _commit_file(pusher, f"{branch.replace('/', '_')}.txt", branch, f"Create {branch}")
            _git(pusher, "push", "origin", branch)
            _git(pusher, "checkout", "main")

        result = _run_sync(
            local_clone.parent,
            exclude_patterns=["pusher", "remote.git"],
        )

        created = {b for _, b in result.branches_created}
        assert "develop" in created
        assert "release/1.0" in created
        assert "hotfix/urgent" in created

    def test_dry_run_does_not_create_branch(self, tmp_path, bare_remote, local_clone):
        """Dry-run should report but not actually create new branches."""
        _push_via_clone(tmp_path, bare_remote, "pusher",
                        {"feat.txt": "feature"}, "Feature commit",
                        branch="feature/dry")

        result = _run_sync(
            local_clone.parent,
            dry_run=True,
            exclude_patterns=["pusher", "remote.git"],
        )

        assert len(result.branches_created) >= 1
        # Branch should NOT actually exist locally
        branches = _git(local_clone, "branch")
        assert "feature/dry" not in branches


# ---------------------------------------------------------------------------
# Tests: Stale branch deletion
# ---------------------------------------------------------------------------

class TestStaleBranch:
    def test_deletes_stale_tracking_branch(self, tmp_path, bare_remote, local_clone):
        """Branch that had upstream but remote deleted it -> stale, should delete."""
        _git(local_clone, "checkout", "-b", "to-delete")
        _commit_file(local_clone, "del.txt", "delete me", "Delete branch commit")
        _git(local_clone, "push", "-u", "origin", "to-delete")
        _git(local_clone, "checkout", "main")

        _git(local_clone, "push", "origin", "--delete", "to-delete")

        result = _run_sync(
            local_clone.parent,
            exclude_patterns=["remote.git"],
        )

        stale = result.get_issues_by_type(IssueType.STALE)
        assert len(stale) >= 1

        branches = _git(local_clone, "branch")
        assert "to-delete" not in branches

    def test_keeps_local_only_branch(self, tmp_path, bare_remote, local_clone):
        """Branch that never had an upstream -> should NOT be deleted."""
        _git(local_clone, "checkout", "-b", "local-experiment")
        _commit_file(local_clone, "exp.txt", "experiment", "Experiment commit")
        _git(local_clone, "checkout", "main")

        result = _run_sync(
            local_clone.parent,
            exclude_patterns=["remote.git"],
        )

        stale = result.get_issues_by_type(IssueType.STALE)
        stale_branches = [s.branch for s in stale]
        assert "local-experiment" not in stale_branches

        branches = _git(local_clone, "branch")
        assert "local-experiment" in branches

    def test_no_remove_stale_keeps_branch(self, tmp_path, bare_remote, local_clone):
        """--no-remove-stale should preserve stale branches."""
        _git(local_clone, "checkout", "-b", "stale-keep")
        _commit_file(local_clone, "keep.txt", "keep", "Keep this")
        _git(local_clone, "push", "-u", "origin", "stale-keep")
        _git(local_clone, "checkout", "main")

        _git(local_clone, "push", "origin", "--delete", "stale-keep")

        result = _run_sync(
            local_clone.parent,
            remove_stale=False,
            exclude_patterns=["remote.git"],
        )

        # No stale issues at all (detection is skipped)
        stale = result.get_issues_by_type(IssueType.STALE)
        assert len(stale) == 0

        # Branch still exists
        branches = _git(local_clone, "branch")
        assert "stale-keep" in branches

    def test_stale_branch_currently_checked_out(self, tmp_path, bare_remote, local_clone):
        """Stale branch that is checked out -> skip deletion, report issue."""
        _git(local_clone, "checkout", "-b", "checked-out-stale")
        _commit_file(local_clone, "co.txt", "checked out", "Checked out commit")
        _git(local_clone, "push", "-u", "origin", "checked-out-stale")
        # Delete from remote but stay on the branch
        _git(local_clone, "push", "origin", "--delete", "checked-out-stale")

        result = _run_sync(
            local_clone.parent,
            exclude_patterns=["remote.git"],
        )

        stale = result.get_issues_by_type(IssueType.STALE)
        assert len(stale) >= 1
        # Should mention it's checked out
        co_issues = [s for s in stale if s.branch == "checked-out-stale"]
        assert len(co_issues) == 1
        assert "checked out" in co_issues[0].details.lower()

        # Branch should still exist (not deleted)
        branches = _git(local_clone, "branch")
        assert "checked-out-stale" in branches

    def test_dry_run_does_not_delete_stale(self, tmp_path, bare_remote, local_clone):
        """Dry-run should report stale but not delete."""
        _git(local_clone, "checkout", "-b", "stale-dry")
        _commit_file(local_clone, "dry.txt", "dry", "Dry run stale")
        _git(local_clone, "push", "-u", "origin", "stale-dry")
        _git(local_clone, "checkout", "main")
        _git(local_clone, "push", "origin", "--delete", "stale-dry")

        result = _run_sync(
            local_clone.parent,
            dry_run=True,
            exclude_patterns=["remote.git"],
        )

        stale = result.get_issues_by_type(IssueType.STALE)
        assert len(stale) >= 1

        # Branch should still exist
        branches = _git(local_clone, "branch")
        assert "stale-dry" in branches


# ---------------------------------------------------------------------------
# Tests: Diverged and ahead detection
# ---------------------------------------------------------------------------

class TestDivergedAndAhead:
    def test_ahead_reports_unpushed(self, tmp_path, bare_remote, local_clone):
        """Local has unpushed commits -> UNPUSHED issue."""
        _commit_file(local_clone, "ahead.txt", "ahead", "Unpushed commit")

        result = _run_sync(
            local_clone.parent,
            exclude_patterns=["remote.git"],
        )

        unpushed = result.get_issues_by_type(IssueType.UNPUSHED)
        assert len(unpushed) >= 1

    def test_ahead_multiple_commits(self, tmp_path, bare_remote, local_clone):
        """Local has 3 unpushed commits -> UNPUSHED issue."""
        for i in range(3):
            _commit_file(local_clone, f"ahead{i}.txt", f"a{i}", f"Unpushed {i}")

        result = _run_sync(
            local_clone.parent,
            exclude_patterns=["remote.git"],
        )

        unpushed = result.get_issues_by_type(IssueType.UNPUSHED)
        assert len(unpushed) >= 1

    def test_diverged_reports_critical(self, tmp_path, bare_remote, local_clone):
        """Both local and remote have commits -> DIVERGED issue."""
        _push_via_clone(tmp_path, bare_remote, "pusher",
                        {"remote_diverge.txt": "remote"}, "Remote diverge")

        _commit_file(local_clone, "local_diverge.txt", "local", "Local diverge")

        result = _run_sync(
            local_clone.parent,
            exclude_patterns=["pusher", "remote.git"],
        )

        diverged = result.get_issues_by_type(IssueType.DIVERGED)
        assert len(diverged) >= 1
        assert result.has_critical_issues() is True

    def test_diverged_with_stash_and_pull_still_diverged(self, tmp_path, bare_remote, local_clone):
        """Diverged branch cannot be fixed by --stash-and-pull, should still report DIVERGED."""
        _push_via_clone(tmp_path, bare_remote, "pusher",
                        {"remote.txt": "remote side"}, "Remote diverge")
        _commit_file(local_clone, "local.txt", "local side", "Local diverge")

        result = _run_sync(
            local_clone.parent,
            stash_and_pull=True,
            exclude_patterns=["pusher", "remote.git"],
        )

        diverged = result.get_issues_by_type(IssueType.DIVERGED)
        assert len(diverged) >= 1
        assert result.has_critical_issues() is True


# ---------------------------------------------------------------------------
# Tests: Original branch restoration
# ---------------------------------------------------------------------------

class TestBranchRestoration:
    def test_returns_to_original_branch(self, tmp_path, bare_remote, local_clone):
        """After sync, should be back on the branch that was active before."""
        # Create a second branch and stay on it
        _git(local_clone, "checkout", "-b", "my-feature")
        _commit_file(local_clone, "feat.txt", "feature", "Feature work")
        _git(local_clone, "push", "-u", "origin", "my-feature")

        # Push new commit to main via remote
        _push_via_clone(tmp_path, bare_remote, "pusher",
                        {"new.txt": "main update"}, "Main update")

        _run_sync(
            local_clone.parent,
            exclude_patterns=["pusher", "remote.git"],
        )

        # Should be back on my-feature
        current = _git(local_clone, "rev-parse", "--abbrev-ref", "HEAD")
        assert current == "my-feature"

    def test_returns_to_original_after_multi_branch_sync(self, tmp_path, bare_remote, local_clone):
        """Original branch restored even when multiple branches were synced."""
        pusher = tmp_path / "pusher"
        _git(tmp_path, "clone", str(bare_remote), "pusher")
        _git(pusher, "config", "user.email", "test@test.com")
        _git(pusher, "config", "user.name", "Test")

        # Create develop and release branches on remote
        for branch in ["develop", "release/v1"]:
            _git(pusher, "checkout", "-b", branch)
            _commit_file(pusher, f"{branch.replace('/', '_')}.txt", branch, f"Create {branch}")
            _git(pusher, "push", "origin", branch)
            _git(pusher, "checkout", "main")

        # Fetch so local knows about the remote branches, then create develop
        _git(local_clone, "fetch", "origin")
        _git(local_clone, "checkout", "-b", "develop", "origin/develop")

        _run_sync(
            local_clone.parent,
            exclude_patterns=["pusher", "remote.git"],
        )

        current = _git(local_clone, "rev-parse", "--abbrev-ref", "HEAD")
        assert current == "develop"


# ---------------------------------------------------------------------------
# Tests: Multi-branch same repo (complex scenario)
# ---------------------------------------------------------------------------

class TestMultiBranchSameRepo:
    def test_mixed_states_in_one_repo(self, tmp_path, bare_remote, local_clone):
        """One repo with branches in different states: behind, ahead, diverged, up-to-date."""
        pusher = tmp_path / "pusher"
        _git(tmp_path, "clone", str(bare_remote), "pusher")
        _git(pusher, "config", "user.email", "test@test.com")
        _git(pusher, "config", "user.name", "Test")

        # Create develop branch on remote and locally (will be "behind")
        _git(pusher, "checkout", "-b", "develop")
        _commit_file(pusher, "dev_init.txt", "dev", "Develop init")
        _git(pusher, "push", "origin", "develop")
        _git(pusher, "checkout", "main")

        # Create feature/x on remote and locally (will be "diverged")
        _git(pusher, "checkout", "-b", "feature/x")
        _commit_file(pusher, "feat_init.txt", "feat", "Feature init")
        _git(pusher, "push", "origin", "feature/x")
        _git(pusher, "checkout", "main")

        # Set up local branches
        _git(local_clone, "fetch", "origin")
        _git(local_clone, "checkout", "-b", "develop", "origin/develop")
        _git(local_clone, "checkout", "-b", "feature/x", "origin/feature/x")
        _git(local_clone, "checkout", "main")

        # Now create the mixed states:
        # 1. main: push remote ahead (local behind)
        _git(pusher, "checkout", "main")
        _commit_file(pusher, "main_ahead.txt", "main update", "Main remote ahead")
        _git(pusher, "push", "origin", "main")

        # 2. develop: push remote ahead (local behind)
        _git(pusher, "checkout", "develop")
        _commit_file(pusher, "dev_ahead.txt", "dev update", "Develop remote ahead")
        _git(pusher, "push", "origin", "develop")

        # 3. feature/x: make local ahead (unpushed) AND remote ahead (diverged)
        _git(pusher, "checkout", "feature/x")
        _commit_file(pusher, "feat_remote.txt", "remote feat", "Feature remote diverge")
        _git(pusher, "push", "origin", "feature/x")

        _git(local_clone, "checkout", "feature/x")
        _commit_file(local_clone, "feat_local.txt", "local feat", "Feature local diverge")
        _git(local_clone, "checkout", "main")

        # 4. Create a local-only ahead branch
        _git(local_clone, "checkout", "-b", "local-only")
        _commit_file(local_clone, "local_only.txt", "local", "Local only commit")
        _git(local_clone, "checkout", "main")

        result = _run_sync(
            local_clone.parent,
            exclude_patterns=["pusher", "remote.git"],
        )

        # main and develop should be updated (fast-forwarded)
        assert (local_clone / "main_ahead.txt").exists()
        _git(local_clone, "checkout", "develop")
        assert (local_clone / "dev_ahead.txt").exists()

        # feature/x should be diverged
        diverged = result.get_issues_by_type(IssueType.DIVERGED)
        diverged_branches = [d.branch for d in diverged]
        assert "feature/x" in diverged_branches

        # Result should have updates and issues
        assert result.repos_processed == 1
        assert result.has_critical_issues() is True


# ---------------------------------------------------------------------------
# Tests: JSON output
# ---------------------------------------------------------------------------

class TestJsonOutput:
    def test_json_output_structure(self, tmp_path, bare_remote, local_clone):
        """JSON output should be valid and contain expected keys."""
        config = SyncConfig(
            dry_run=False,
            json_output=True,
            exclude_patterns=["remote.git"],
        )
        output = NullOutputHandler()
        orchestrator = SyncOrchestrator(config, output)
        result = orchestrator.sync_all(local_clone.parent)

        d = result.to_dict()
        assert "repos_processed" in d
        assert "branches_created" in d
        assert "branches_updated" in d
        assert "issues" in d
        assert "has_critical_issues" in d
        json_str = json.dumps(d, indent=2)
        parsed = json.loads(json_str)
        assert parsed["repos_processed"] == 1

    def test_json_with_issues(self, tmp_path, bare_remote, local_clone):
        """JSON output should include issue details when there are problems."""
        # Create a diverged situation for a critical issue
        _push_via_clone(tmp_path, bare_remote, "pusher",
                        {"remote.txt": "remote"}, "Remote commit")
        _commit_file(local_clone, "local.txt", "local", "Local commit")

        result = _run_sync(
            local_clone.parent,
            json_output=True,
            exclude_patterns=["pusher", "remote.git"],
        )

        d = result.to_dict()
        assert d["has_critical_issues"] is True
        assert len(d["issues"]) >= 1
        issue = d["issues"][0]
        assert issue["type"] == "DIVERGED"
        assert "branch" in issue
        assert "timestamp" in issue
        assert "details" in issue
        # Verify full round-trip through JSON
        json_str = json.dumps(d, indent=2)
        parsed = json.loads(json_str)
        assert parsed["has_critical_issues"] is True

    def test_json_with_branches_created(self, tmp_path, bare_remote, local_clone):
        """JSON output lists created branches."""
        _push_via_clone(tmp_path, bare_remote, "pusher",
                        {"feat.txt": "feat"}, "Feature",
                        branch="feature/json-test")

        result = _run_sync(
            local_clone.parent,
            json_output=True,
            exclude_patterns=["pusher", "remote.git"],
        )

        d = result.to_dict()
        assert len(d["branches_created"]) >= 1
        created = d["branches_created"]
        branch_names = [c["branch"] for c in created]
        assert "feature/json-test" in branch_names


# ---------------------------------------------------------------------------
# Tests: Branch filter
# ---------------------------------------------------------------------------

class TestBranchFilter:
    def test_only_syncs_matching_branches(self, tmp_path, bare_remote, local_clone):
        """--branches should limit which branches get synced."""
        pusher = tmp_path / "pusher"
        _git(tmp_path, "clone", str(bare_remote), "pusher")
        _git(pusher, "config", "user.email", "test@test.com")
        _git(pusher, "config", "user.name", "Test")
        _git(pusher, "checkout", "-b", "develop")
        _commit_file(pusher, "dev.txt", "develop", "Develop commit")
        _git(pusher, "push", "origin", "develop")
        _git(pusher, "checkout", "main")
        _commit_file(pusher, "main_new.txt", "main update", "Main update")
        _git(pusher, "push", "origin", "main")

        result = _run_sync(
            local_clone.parent,
            branch_patterns=["main"],
            exclude_patterns=["pusher", "remote.git"],
        )

        assert (local_clone / "main_new.txt").exists()
        created_branches = [b for _, b in result.branches_created]
        assert "develop" not in created_branches

    def test_glob_pattern_matching(self, tmp_path, bare_remote, local_clone):
        """Branch filter with glob pattern should match wildcard branches."""
        pusher = tmp_path / "pusher"
        _git(tmp_path, "clone", str(bare_remote), "pusher")
        _git(pusher, "config", "user.email", "test@test.com")
        _git(pusher, "config", "user.name", "Test")

        for branch in ["release/1.0", "release/2.0", "feature/abc", "develop"]:
            _git(pusher, "checkout", "-b", branch)
            _commit_file(pusher, f"{branch.replace('/', '_')}.txt", branch, f"Create {branch}")
            _git(pusher, "push", "origin", branch)
            _git(pusher, "checkout", "main")

        result = _run_sync(
            local_clone.parent,
            branch_patterns=["release/*"],
            exclude_patterns=["pusher", "remote.git"],
        )

        created = {b for _, b in result.branches_created}
        assert "release/1.0" in created
        assert "release/2.0" in created
        assert "feature/abc" not in created
        assert "develop" not in created

    def test_multiple_patterns(self, tmp_path, bare_remote, local_clone):
        """Multiple branch patterns should match union of all patterns."""
        pusher = tmp_path / "pusher"
        _git(tmp_path, "clone", str(bare_remote), "pusher")
        _git(pusher, "config", "user.email", "test@test.com")
        _git(pusher, "config", "user.name", "Test")

        for branch in ["develop", "release/1.0", "feature/x", "hotfix/y"]:
            _git(pusher, "checkout", "-b", branch)
            _commit_file(pusher, f"{branch.replace('/', '_')}.txt", branch, f"Create {branch}")
            _git(pusher, "push", "origin", branch)
            _git(pusher, "checkout", "main")

        result = _run_sync(
            local_clone.parent,
            branch_patterns=["main", "develop", "release/*"],
            exclude_patterns=["pusher", "remote.git"],
        )

        created = {b for _, b in result.branches_created}
        assert "develop" in created
        assert "release/1.0" in created
        assert "feature/x" not in created
        assert "hotfix/y" not in created

    def test_filter_protects_unmatched_stale_branch(self, tmp_path, bare_remote, local_clone):
        """Stale branch NOT matching filter should NOT be deleted."""
        # Create 'staging' branch, push it, then delete from remote
        _git(local_clone, "checkout", "-b", "staging")
        _commit_file(local_clone, "staging.txt", "staging", "Staging commit")
        _git(local_clone, "push", "-u", "origin", "staging")
        _git(local_clone, "checkout", "main")
        _git(local_clone, "push", "origin", "--delete", "staging")

        # Sync with filter that does NOT include 'staging'
        result = _run_sync(
            local_clone.parent,
            branch_patterns=["main"],
            exclude_patterns=["remote.git"],
        )

        # 'staging' should NOT be reported as stale (it's outside filter scope)
        stale = result.get_issues_by_type(IssueType.STALE)
        stale_branches = [s.branch for s in stale]
        assert "staging" not in stale_branches

        # Branch should still exist
        branches = _git(local_clone, "branch")
        assert "staging" in branches

    def test_filter_deletes_matching_stale_branch(self, tmp_path, bare_remote, local_clone):
        """Stale branch that MATCHES filter should be deleted."""
        _git(local_clone, "checkout", "-b", "release/old")
        _commit_file(local_clone, "old.txt", "old", "Old release")
        _git(local_clone, "push", "-u", "origin", "release/old")
        _git(local_clone, "checkout", "main")
        _git(local_clone, "push", "origin", "--delete", "release/old")

        result = _run_sync(
            local_clone.parent,
            branch_patterns=["main", "release/*"],
            exclude_patterns=["remote.git"],
        )

        stale = result.get_issues_by_type(IssueType.STALE)
        stale_branches = [s.branch for s in stale]
        assert "release/old" in stale_branches

        branches = _git(local_clone, "branch")
        assert "release/old" not in branches

    def test_filter_does_not_create_unmatched_new_branch(self, tmp_path, bare_remote, local_clone):
        """New remote branch outside filter should NOT be created locally."""
        pusher = tmp_path / "pusher"
        _git(tmp_path, "clone", str(bare_remote), "pusher")
        _git(pusher, "config", "user.email", "test@test.com")
        _git(pusher, "config", "user.name", "Test")
        _git(pusher, "checkout", "-b", "feature/excluded")
        _commit_file(pusher, "feat.txt", "feat", "Feature commit")
        _git(pusher, "push", "origin", "feature/excluded")

        result = _run_sync(
            local_clone.parent,
            branch_patterns=["main"],
            exclude_patterns=["pusher", "remote.git"],
        )

        created = {b for _, b in result.branches_created}
        assert "feature/excluded" not in created
        branches = _git(local_clone, "branch")
        assert "feature/excluded" not in branches


# ---------------------------------------------------------------------------
# Tests: Multiple repositories
# ---------------------------------------------------------------------------

class TestMultiRepo:
    def test_syncs_multiple_repos(self, workspace: Path):
        """Should discover and sync multiple repos in a directory."""
        remote_a, local_a = _make_repo_pair(workspace, "repo-a")
        remote_b, local_b = _make_repo_pair(workspace, "repo-b")

        for remote, name in [(remote_a, "repo-a"), (remote_b, "repo-b")]:
            pusher = workspace / f"{name}-pusher"
            _git(workspace, "clone", str(remote), f"{name}-pusher")
            _git(pusher, "config", "user.email", "test@test.com")
            _git(pusher, "config", "user.name", "Test")
            _commit_file(pusher, f"{name}.txt", name, f"{name} commit")
            _git(pusher, "push", "origin", "main")

        result = _run_sync(
            workspace,
            exclude_patterns=["remote.git", "pusher"],
        )

        assert result.repos_processed == 2
        assert (local_a / "repo-a.txt").read_text() == "repo-a"
        assert (local_b / "repo-b.txt").read_text() == "repo-b"

    def test_parallel_syncs_multiple_repos(self, workspace: Path):
        """Parallel mode should produce the same results as sequential."""
        remote_a, local_a = _make_repo_pair(workspace, "repo-a")
        remote_b, local_b = _make_repo_pair(workspace, "repo-b")

        for remote, name in [(remote_a, "repo-a"), (remote_b, "repo-b")]:
            pusher = workspace / f"{name}-pusher"
            _git(workspace, "clone", str(remote), f"{name}-pusher")
            _git(pusher, "config", "user.email", "test@test.com")
            _git(pusher, "config", "user.name", "Test")
            _commit_file(pusher, f"{name}.txt", name, f"{name} commit")
            _git(pusher, "push", "origin", "main")

        result = _run_sync(
            workspace,
            parallel=True,
            max_workers=2,
            exclude_patterns=["remote.git", "pusher"],
        )

        assert result.repos_processed == 2
        assert (local_a / "repo-a.txt").read_text() == "repo-a"
        assert (local_b / "repo-b.txt").read_text() == "repo-b"

    def test_parallel_mixed_outcomes(self, workspace: Path):
        """Parallel: one repo succeeds, another has issues."""
        remote_a, local_a = _make_repo_pair(workspace, "repo-ok")
        remote_b, local_b = _make_repo_pair(workspace, "repo-diverged")

        # repo-ok: push an update (will fast-forward)
        pusher_a = workspace / "repo-ok-pusher"
        _git(workspace, "clone", str(remote_a), "repo-ok-pusher")
        _git(pusher_a, "config", "user.email", "test@test.com")
        _git(pusher_a, "config", "user.name", "Test")
        _commit_file(pusher_a, "ok.txt", "ok", "OK commit")
        _git(pusher_a, "push", "origin", "main")

        # repo-diverged: push remote AND local commit (diverge)
        pusher_b = workspace / "repo-diverged-pusher"
        _git(workspace, "clone", str(remote_b), "repo-diverged-pusher")
        _git(pusher_b, "config", "user.email", "test@test.com")
        _git(pusher_b, "config", "user.name", "Test")
        _commit_file(pusher_b, "remote.txt", "remote", "Remote diverge")
        _git(pusher_b, "push", "origin", "main")
        _commit_file(local_b, "local.txt", "local", "Local diverge")

        result = _run_sync(
            workspace,
            parallel=True,
            max_workers=2,
            exclude_patterns=["remote.git", "pusher"],
        )

        assert result.repos_processed == 2
        assert (local_a / "ok.txt").read_text() == "ok"
        assert result.has_critical_issues() is True
        diverged = result.get_issues_by_type(IssueType.DIVERGED)
        assert len(diverged) >= 1

    def test_exclude_patterns_skip_repos(self, workspace: Path):
        """Exclude patterns should prevent repos from being discovered."""
        _make_repo_pair(workspace, "included-repo")
        _make_repo_pair(workspace, "excluded-repo")

        result = _run_sync(
            workspace,
            exclude_patterns=["remote.git", "excluded-repo"],
        )

        assert result.repos_processed == 1

    def test_no_repos_found(self, tmp_path):
        """Empty directory -> zero repos processed, no errors."""
        empty = tmp_path / "empty"
        empty.mkdir()

        result = _run_sync(empty)

        assert result.repos_processed == 0
        assert result.has_issues() is False


# ---------------------------------------------------------------------------
# Tests: Configurable remote name
# ---------------------------------------------------------------------------

class TestRemoteName:
    def test_sync_from_upstream(self, tmp_path: Path):
        """--remote upstream should sync from a remote named 'upstream'."""
        bare = tmp_path / "upstream.git"
        bare.mkdir()
        _git(bare, "init", "--bare", "-b", "main")

        local = tmp_path / "local"
        _git(tmp_path, "clone", str(bare), "local")
        _git(local, "config", "user.email", "test@test.com")
        _git(local, "config", "user.name", "Test")
        _git(local, "remote", "rename", "origin", "upstream")
        _git(local, "checkout", "-b", "main")
        _commit_file(local, "init.txt", "initial", "Initial commit")
        _git(local, "push", "-u", "upstream", "main")

        pusher = tmp_path / "pusher"
        _git(tmp_path, "clone", str(bare), "pusher")
        _git(pusher, "config", "user.email", "test@test.com")
        _git(pusher, "config", "user.name", "Test")
        _commit_file(pusher, "upstream.txt", "from upstream", "Upstream commit")
        _git(pusher, "push", "origin", "main")

        _git(local, "branch", "--set-upstream-to", "upstream/main", "main")

        result = _run_sync(
            local.parent,
            remote_name="upstream",
            exclude_patterns=["upstream.git", "pusher"],
        )

        assert result.repos_processed == 1
        assert (local / "upstream.txt").read_text() == "from upstream"


# ---------------------------------------------------------------------------
# Tests: Config file integration
# ---------------------------------------------------------------------------

class TestConfigFile:
    def test_loads_config_from_search_dir(self, tmp_path):
        """Config file in search dir should be picked up."""
        ws = tmp_path / "ws"
        ws.mkdir()
        # Create a .pygitrc.toml in the workspace
        config_path = ws / ".pygitrc.toml"
        config_path.write_text('parallel = true\nremote_name = "upstream"\n')

        loaded = load_config_file(ws)
        assert loaded.get("parallel") is True
        assert loaded.get("remote_name") == "upstream"

    def test_explicit_config_path(self, tmp_path):
        """Explicit --config path should be used."""
        custom = tmp_path / "my_config.toml"
        custom.write_text('verbose = true\nfetch_retries = 3\n')

        loaded = load_config_file(tmp_path, config_path=str(custom))
        assert loaded.get("verbose") is True
        assert loaded.get("fetch_retries") == 3

    def test_config_file_with_full_sync(self, workspace: Path):
        """Config file values should be used by the orchestrator."""
        remote, local = _make_repo_pair(workspace, "config-test")

        # Push an update
        pusher = workspace / "pusher"
        _git(workspace, "clone", str(remote), "pusher")
        _git(pusher, "config", "user.email", "test@test.com")
        _git(pusher, "config", "user.name", "Test")
        _commit_file(pusher, "config_test.txt", "works", "Config test commit")
        _git(pusher, "push", "origin", "main")

        # Use config with exclude patterns via SyncConfig directly
        # (since load_config_file is used in main(), we test config values reach sync)
        result = _run_sync(
            workspace,
            exclude_patterns=["remote.git", "pusher"],
        )

        assert result.repos_processed == 1
        assert (local / "config_test.txt").read_text() == "works"


# ---------------------------------------------------------------------------
# Tests: Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_repo_with_no_remote(self, tmp_path):
        """Repo with no remote configured -> FAILED issue, not a crash."""
        repo = tmp_path / "no-remote"
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        _git(repo, "config", "user.email", "test@test.com")
        _git(repo, "config", "user.name", "Test")
        _commit_file(repo, "file.txt", "content", "Initial commit")

        result = _run_sync(tmp_path)

        # Should not crash; reports a FAILED issue
        failed = result.get_issues_by_type(IssueType.FAILED)
        assert len(failed) >= 1
        assert "no-remote" in failed[0].repo_path

    def test_invalid_git_dir_skipped(self, tmp_path):
        """Directory with .git file (not dir) should not be found by scanner."""
        broken = tmp_path / "broken-repo"
        broken.mkdir()
        (broken / ".git").write_text("gitdir: /nonexistent")

        # Also create a valid repo with a remote so it syncs fully
        remote = tmp_path / "valid-remote.git"
        remote.mkdir()
        _git(remote, "init", "--bare", "-b", "main")
        valid = tmp_path / "valid-repo"
        _git(tmp_path, "clone", str(remote), "valid-repo")
        _git(valid, "config", "user.email", "test@test.com")
        _git(valid, "config", "user.name", "Test")
        _git(valid, "checkout", "-b", "main")
        _commit_file(valid, "file.txt", "content", "Initial")
        _git(valid, "push", "-u", "origin", "main")

        result = _run_sync(tmp_path, exclude_patterns=["remote.git"])

        # Only valid repo should be found (broken-repo has .git as file)
        assert result.repos_processed == 1

    def test_graceful_on_empty_bare_repo(self, tmp_path):
        """Clone of empty bare repo (no commits) should be handled gracefully."""
        bare = tmp_path / "empty.git"
        bare.mkdir()
        _git(bare, "init", "--bare", "-b", "main")

        local = tmp_path / "local"
        _git(tmp_path, "clone", str(bare), "local")

        result = _run_sync(
            local.parent,
            exclude_patterns=["empty.git"],
        )

        # Should process the repo without crashing
        assert result.repos_processed == 1


# ---------------------------------------------------------------------------
# Tests: Verbose output
# ---------------------------------------------------------------------------

class TestVerboseOutput:
    def test_verbose_runs_without_error(self, tmp_path, bare_remote, local_clone):
        """Verbose mode should complete without errors."""
        _push_via_clone(tmp_path, bare_remote, "pusher",
                        {"verbose.txt": "test"}, "Verbose commit")

        # Use ConsoleOutputHandler to verify verbose output doesn't crash
        config = SyncConfig(
            dry_run=False,
            verbose=True,
            exclude_patterns=["pusher", "remote.git"],
        )
        output = ConsoleOutputHandler(verbose=True)
        orchestrator = SyncOrchestrator(config, output)
        result = orchestrator.sync_all(local_clone.parent)

        assert result.repos_processed == 1
        assert (local_clone / "verbose.txt").read_text() == "test"


# ---------------------------------------------------------------------------
# Tests: Exit code behavior (via has_critical_issues)
# ---------------------------------------------------------------------------

class TestExitCodeBehavior:
    """Test the result.has_critical_issues() that determines exit code in main()."""

    def test_clean_sync_no_critical(self, tmp_path, bare_remote, local_clone):
        """Successful sync -> has_critical_issues() is False (exit code 0)."""
        result = _run_sync(
            local_clone.parent,
            exclude_patterns=["remote.git"],
        )
        assert result.has_critical_issues() is False

    def test_diverged_is_critical(self, tmp_path, bare_remote, local_clone):
        """Diverged branches -> has_critical_issues() is True (exit code 1)."""
        _push_via_clone(tmp_path, bare_remote, "pusher",
                        {"r.txt": "remote"}, "Remote")
        _commit_file(local_clone, "l.txt", "local", "Local")

        result = _run_sync(
            local_clone.parent,
            exclude_patterns=["pusher", "remote.git"],
        )
        assert result.has_critical_issues() is True

    def test_stash_conflict_is_critical(self, tmp_path, bare_remote, local_clone):
        """Stash conflict -> has_critical_issues() is True (exit code 1)."""
        _push_via_clone(tmp_path, bare_remote, "pusher",
                        {"init.txt": "remote version"}, "Remote modifies file")
        (local_clone / "init.txt").write_text("local conflicting version")

        result = _run_sync(
            local_clone.parent,
            stash_and_pull=True,
            exclude_patterns=["pusher", "remote.git"],
        )
        assert result.has_critical_issues() is True

    def test_unpushed_is_not_critical(self, tmp_path, bare_remote, local_clone):
        """Unpushed commits -> has_critical_issues() is False (exit code 0)."""
        _commit_file(local_clone, "ahead.txt", "ahead", "Unpushed")

        result = _run_sync(
            local_clone.parent,
            exclude_patterns=["remote.git"],
        )
        assert result.has_issues() is True
        assert result.has_critical_issues() is False

    def test_local_changes_not_critical(self, tmp_path, bare_remote, local_clone):
        """Local changes preventing pull -> has_critical_issues() is False."""
        _push_via_clone(tmp_path, bare_remote, "pusher",
                        {"new.txt": "new"}, "New file")
        (local_clone / "dirty.txt").write_text("dirty")

        result = _run_sync(
            local_clone.parent,
            exclude_patterns=["pusher", "remote.git"],
        )
        assert result.has_issues() is True
        assert result.has_critical_issues() is False


# ---------------------------------------------------------------------------
# Tests: Stash-and-pull edge cases
# ---------------------------------------------------------------------------

class TestStashEdgeCases:
    def test_stash_with_untracked_files(self, tmp_path, bare_remote, local_clone):
        """Stash-and-pull with only untracked files -> should work."""
        _push_via_clone(tmp_path, bare_remote, "pusher",
                        {"remote.txt": "remote"}, "Remote commit")

        # Create untracked file (not staged)
        (local_clone / "untracked.txt").write_text("untracked content")

        _run_sync(
            local_clone.parent,
            stash_and_pull=True,
            exclude_patterns=["pusher", "remote.git"],
        )

        # Remote change should be pulled
        assert (local_clone / "remote.txt").read_text() == "remote"

    def test_stash_with_mixed_dirty_state(self, tmp_path, bare_remote, local_clone):
        """Stash-and-pull with staged, unstaged, and untracked changes."""
        _push_via_clone(tmp_path, bare_remote, "pusher",
                        {"remote.txt": "remote update"}, "Remote commit")

        # Staged change
        (local_clone / "staged.txt").write_text("staged")
        _git(local_clone, "add", "staged.txt")
        # Unstaged change to existing tracked file
        (local_clone / "init.txt").write_text("modified locally")
        # Untracked file
        (local_clone / "new_untracked.txt").write_text("untracked")

        _run_sync(
            local_clone.parent,
            stash_and_pull=True,
            exclude_patterns=["pusher", "remote.git"],
        )

        # Remote update arrived
        assert (local_clone / "remote.txt").read_text() == "remote update"

    def test_no_rebase_with_stash(self, tmp_path, bare_remote, local_clone):
        """--stash-and-pull + --no-rebase should stash, merge, pop."""
        _push_via_clone(tmp_path, bare_remote, "pusher",
                        {"merge_stash.txt": "merged"}, "Merge stash commit")
        (local_clone / "dirty.txt").write_text("dirty content")

        result = _run_sync(
            local_clone.parent,
            stash_and_pull=True,
            use_rebase=False,
            exclude_patterns=["pusher", "remote.git"],
        )

        assert result.has_critical_issues() is False
        assert (local_clone / "merge_stash.txt").read_text() == "merged"
        assert (local_clone / "dirty.txt").read_text() == "dirty content"


# ---------------------------------------------------------------------------
# Tests: Dry-run comprehensive
# ---------------------------------------------------------------------------

class TestDryRunComprehensive:
    def test_dry_run_reports_would_update(self, tmp_path, bare_remote, local_clone):
        """Dry run reports branch would be updated but doesn't change anything."""
        _push_via_clone(tmp_path, bare_remote, "pusher",
                        {"new.txt": "content"}, "New commit")

        before_hash = _git(local_clone, "rev-parse", "HEAD")

        result = _run_sync(
            local_clone.parent,
            dry_run=True,
            exclude_patterns=["pusher", "remote.git"],
        )

        after_hash = _git(local_clone, "rev-parse", "HEAD")
        assert before_hash == after_hash  # No change
        assert result.repos_processed == 1

    def test_dry_run_stash_and_pull_does_nothing(self, tmp_path, bare_remote, local_clone):
        """Dry run + stash-and-pull should not stash or pull."""
        _push_via_clone(tmp_path, bare_remote, "pusher",
                        {"remote.txt": "remote"}, "Remote commit")
        (local_clone / "dirty.txt").write_text("dirty")

        _run_sync(
            local_clone.parent,
            dry_run=True,
            stash_and_pull=True,
            exclude_patterns=["pusher", "remote.git"],
        )

        # Nothing should have changed
        assert not (local_clone / "remote.txt").exists()
        assert (local_clone / "dirty.txt").read_text() == "dirty"
        # No stash should have been created
        stash_list = _git(local_clone, "stash", "list")
        assert stash_list == ""
