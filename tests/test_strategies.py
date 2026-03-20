"""Tests for branch sync strategy classes."""

from pathlib import Path
from typing import Optional

from pygit_sync import (
    AheadOfRemoteStrategy,
    BranchInfo,
    BranchStatus,
    BranchSynchronizer,
    CleanFastForwardStrategy,
    DirtyWorkingTreeStrategy,
    DivergedBranchStrategy,
    IssueType,
    NullOutputHandler,
    OperationResult,
    OperationType,
    SyncConfig,
    UpToDateStrategy,
)


class FakeGitRepository:
    """Fake git repository for testing strategies."""

    def __init__(self, *, clean: bool = True):
        self._clean = clean
        self._path = Path("/tmp/fake-repo")
        self._current_branch = "main"
        self.pull_success = True
        self.stash_push_success = True
        self.stash_pop_success = True

    @property
    def path(self) -> Path:
        return self._path

    @property
    def current_branch(self) -> Optional[str]:
        return self._current_branch

    def is_clean(self) -> bool:
        return self._clean

    def fetch(self, remote: str = "origin", prune: bool = True) -> OperationResult:
        return OperationResult(True, OperationType.FETCH, "OK")

    def checkout(self, branch: str) -> OperationResult:
        self._current_branch = branch
        return OperationResult(True, OperationType.CHECKOUT, f"Checked out {branch}")

    def pull(self, remote: str, branch: str, rebase: bool = False) -> OperationResult:
        op = OperationType.REBASE if rebase else OperationType.PULL
        if self.pull_success:
            return OperationResult(True, op, "Pulled")
        return OperationResult(False, op, "Pull failed")

    def create_branch(self, name: str, start_point: str) -> OperationResult:
        return OperationResult(True, OperationType.BRANCH_CREATE, f"Created {name}")

    def delete_branch(self, name: str, force: bool = False) -> OperationResult:
        return OperationResult(True, OperationType.BRANCH_DELETE, f"Deleted {name}")

    def stash_push(self, message: str, include_untracked: bool = True) -> OperationResult:
        if self.stash_push_success:
            return OperationResult(True, OperationType.STASH, "Stashed")
        return OperationResult(False, OperationType.STASH, "Stash failed")

    def stash_pop(self) -> OperationResult:
        if self.stash_pop_success:
            return OperationResult(True, OperationType.STASH, "Popped")
        return OperationResult(False, OperationType.STASH, "Pop failed")

    def get_local_branches(self) -> list[BranchInfo]:
        return []

    def get_remote_branches(self, remote: str = "origin") -> list[BranchInfo]:
        return []

    def get_branch_status(self, branch: str) -> BranchStatus:
        return BranchStatus()

    def get_change_counts(self) -> dict[str, int]:
        if self._clean:
            return {'staged': 0, 'unstaged': 0, 'untracked': 0}
        return {'staged': 1, 'unstaged': 3, 'untracked': 2}

    def close(self) -> None:
        pass


# --- CleanFastForwardStrategy ---

class TestCleanFastForwardStrategy:
    def _make(self, repo=None, config=None):
        repo = repo or FakeGitRepository(clean=True)
        config = config or SyncConfig(dry_run=False)
        return CleanFastForwardStrategy(repo, NullOutputHandler(), config), repo

    def test_can_handle_clean_behind(self):
        strategy, _ = self._make()
        status = BranchStatus(exists=True, has_upstream=True, commits_behind=3)
        branch = BranchInfo(name="main", is_remote=False)
        assert strategy.can_handle(branch, status) is True

    def test_cannot_handle_dirty(self):
        repo = FakeGitRepository(clean=False)
        strategy, _ = self._make(repo=repo)
        status = BranchStatus(exists=True, has_upstream=True, commits_behind=3)
        branch = BranchInfo(name="main", is_remote=False)
        assert strategy.can_handle(branch, status) is False

    def test_cannot_handle_ahead(self):
        strategy, _ = self._make()
        status = BranchStatus(exists=True, has_upstream=True, commits_ahead=2)
        branch = BranchInfo(name="main", is_remote=False)
        assert strategy.can_handle(branch, status) is False

    def test_sync_success(self):
        strategy, _ = self._make()
        status = BranchStatus(exists=True, has_upstream=True, commits_behind=3)
        branch = BranchInfo(name="main", is_remote=False)
        result = strategy.sync(branch, "origin", status)
        assert result is None  # No issue = success

    def test_sync_dry_run(self):
        strategy, _ = self._make(config=SyncConfig(dry_run=True))
        status = BranchStatus(exists=True, has_upstream=True, commits_behind=3)
        branch = BranchInfo(name="main", is_remote=False)
        result = strategy.sync(branch, "origin", status)
        assert result is None

    def test_sync_pull_failure(self):
        repo = FakeGitRepository(clean=True)
        repo.pull_success = False
        strategy, _ = self._make(repo=repo)
        status = BranchStatus(exists=True, has_upstream=True, commits_behind=3)
        branch = BranchInfo(name="main", is_remote=False)
        result = strategy.sync(branch, "origin", status)
        assert result is not None
        assert result.issue_type == IssueType.FAILED


# --- DivergedBranchStrategy ---

class TestDivergedBranchStrategy:
    def _make(self):
        repo = FakeGitRepository()
        config = SyncConfig(dry_run=False)
        return DivergedBranchStrategy(repo, NullOutputHandler(), config)

    def test_can_handle_diverged(self):
        strategy = self._make()
        status = BranchStatus(is_diverged=True)
        branch = BranchInfo(name="feat", is_remote=False)
        assert strategy.can_handle(branch, status) is True

    def test_cannot_handle_non_diverged(self):
        strategy = self._make()
        status = BranchStatus(is_diverged=False)
        branch = BranchInfo(name="feat", is_remote=False)
        assert strategy.can_handle(branch, status) is False

    def test_sync_returns_diverged_issue(self):
        strategy = self._make()
        status = BranchStatus(is_diverged=True, commits_ahead=2, commits_behind=3)
        branch = BranchInfo(name="feat", is_remote=False)
        result = strategy.sync(branch, "origin", status)
        assert result is not None
        assert result.issue_type == IssueType.DIVERGED
        assert "2 ahead" in result.details
        assert "3 behind" in result.details


# --- AheadOfRemoteStrategy ---

class TestAheadOfRemoteStrategy:
    def _make(self):
        repo = FakeGitRepository()
        config = SyncConfig(dry_run=False)
        return AheadOfRemoteStrategy(repo, NullOutputHandler(), config)

    def test_can_handle_ahead(self):
        strategy = self._make()
        status = BranchStatus(has_upstream=True, commits_ahead=5, commits_behind=0)
        branch = BranchInfo(name="feat", is_remote=False)
        assert strategy.can_handle(branch, status) is True

    def test_cannot_handle_behind(self):
        strategy = self._make()
        status = BranchStatus(has_upstream=True, commits_ahead=0, commits_behind=2)
        branch = BranchInfo(name="feat", is_remote=False)
        assert strategy.can_handle(branch, status) is False

    def test_sync_returns_unpushed_issue(self):
        strategy = self._make()
        status = BranchStatus(has_upstream=True, commits_ahead=5, commits_behind=0)
        branch = BranchInfo(name="feat", is_remote=False)
        result = strategy.sync(branch, "origin", status)
        assert result is not None
        assert result.issue_type == IssueType.UNPUSHED
        assert "5" in result.details


# --- UpToDateStrategy ---

class TestUpToDateStrategy:
    def _make(self, clean=True):
        repo = FakeGitRepository(clean=clean)
        config = SyncConfig(dry_run=False)
        return UpToDateStrategy(repo, NullOutputHandler(), config)

    def test_can_handle_up_to_date(self):
        strategy = self._make()
        status = BranchStatus(has_upstream=True, commits_ahead=0, commits_behind=0)
        branch = BranchInfo(name="main", is_remote=False)
        assert strategy.can_handle(branch, status) is True

    def test_cannot_handle_behind(self):
        strategy = self._make()
        status = BranchStatus(has_upstream=True, commits_ahead=0, commits_behind=1)
        branch = BranchInfo(name="main", is_remote=False)
        assert strategy.can_handle(branch, status) is False

    def test_sync_returns_none(self):
        strategy = self._make()
        status = BranchStatus(has_upstream=True, commits_ahead=0, commits_behind=0)
        branch = BranchInfo(name="main", is_remote=False)
        result = strategy.sync(branch, "origin", status)
        assert result is None


# --- DirtyWorkingTreeStrategy ---

class TestDirtyWorkingTreeStrategy:
    def _make(self, stash_and_pull=False):
        repo = FakeGitRepository(clean=False)
        config = SyncConfig(dry_run=False, stash_and_pull=stash_and_pull)
        return DirtyWorkingTreeStrategy(repo, NullOutputHandler(), config), repo

    def test_can_handle_dirty_behind(self):
        strategy, _ = self._make()
        status = BranchStatus(exists=True, has_upstream=True, commits_behind=2)
        branch = BranchInfo(name="main", is_remote=False)
        assert strategy.can_handle(branch, status) is True

    def test_cannot_handle_clean(self):
        repo = FakeGitRepository(clean=True)
        config = SyncConfig(dry_run=False)
        strategy = DirtyWorkingTreeStrategy(repo, NullOutputHandler(), config)
        status = BranchStatus(exists=True, has_upstream=True, commits_behind=2)
        branch = BranchInfo(name="main", is_remote=False)
        assert strategy.can_handle(branch, status) is False

    def test_sync_without_stash_returns_local_changes(self):
        strategy, _ = self._make(stash_and_pull=False)
        status = BranchStatus(exists=True, has_upstream=True, commits_behind=2)
        branch = BranchInfo(name="main", is_remote=False)
        result = strategy.sync(branch, "origin", status)
        assert result is not None
        assert result.issue_type == IssueType.LOCAL_CHANGES

    def test_sync_with_stash_success(self):
        strategy, repo = self._make(stash_and_pull=True)
        status = BranchStatus(exists=True, has_upstream=True, commits_behind=2)
        branch = BranchInfo(name="main", is_remote=False)
        result = strategy.sync(branch, "origin", status)
        assert result is None  # Success

    def test_sync_with_stash_pop_conflict(self):
        strategy, repo = self._make(stash_and_pull=True)
        repo.stash_pop_success = False
        status = BranchStatus(exists=True, has_upstream=True, commits_behind=2)
        branch = BranchInfo(name="main", is_remote=False)
        result = strategy.sync(branch, "origin", status)
        assert result is not None
        assert result.issue_type == IssueType.STASH_CONFLICT

    def test_change_description_dirty(self):
        """_get_change_description should report staged/modified/untracked counts."""
        strategy, _ = self._make(stash_and_pull=False)
        desc = strategy._get_change_description()
        assert "1 staged" in desc
        assert "3 modified" in desc
        assert "2 untracked" in desc

    def test_change_description_clean_fallback(self):
        """When repo reports all zeros, should fall back to generic message."""
        repo = FakeGitRepository(clean=True)
        config = SyncConfig(dry_run=False)
        strategy = DirtyWorkingTreeStrategy(repo, NullOutputHandler(), config)
        desc = strategy._get_change_description()
        assert desc == "uncommitted changes"


# --- Branch filter in BranchSynchronizer ---

class TestBranchFilter:
    def test_no_filter_matches_all(self):
        repo = FakeGitRepository()
        config = SyncConfig(dry_run=False, branch_patterns=[])
        sync = BranchSynchronizer(repo, NullOutputHandler(), config)
        assert sync._matches_branch_filter("main") is True
        assert sync._matches_branch_filter("develop") is True
        assert sync._matches_branch_filter("feature/foo") is True

    def test_exact_pattern(self):
        repo = FakeGitRepository()
        config = SyncConfig(dry_run=False, branch_patterns=["main", "develop"])
        sync = BranchSynchronizer(repo, NullOutputHandler(), config)
        assert sync._matches_branch_filter("main") is True
        assert sync._matches_branch_filter("develop") is True
        assert sync._matches_branch_filter("feature/foo") is False

    def test_glob_pattern(self):
        repo = FakeGitRepository()
        config = SyncConfig(dry_run=False, branch_patterns=["release/*", "main"])
        sync = BranchSynchronizer(repo, NullOutputHandler(), config)
        assert sync._matches_branch_filter("main") is True
        assert sync._matches_branch_filter("release/1.0") is True
        assert sync._matches_branch_filter("release/2.0") is True
        assert sync._matches_branch_filter("develop") is False
