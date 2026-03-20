"""Concrete GitPython-based repository implementation."""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path

from git import GitCommandError, Repo

from pygit_sync.models import (
    BranchInfo,
    BranchStatus,
    OperationResult,
    OperationType,
)


class GitPythonRepository:
    """Concrete implementation using GitPython"""

    def __init__(self, repo_path: Path):
        """Open a git repository at the given path."""
        self._path = repo_path
        self._repo = Repo(repo_path)
        self._logger = logging.getLogger(__name__)

    def close(self) -> None:
        """Release underlying git resources."""
        self._repo.close()

    @property
    def path(self) -> Path:
        """Absolute path to the repository root."""
        return self._path

    @property
    def current_branch(self) -> str | None:
        """Name of the checked-out branch, or None if HEAD is detached."""
        try:
            if self._repo.head.is_detached:
                return None
            return self._repo.active_branch.name
        except Exception:
            return None

    def fetch(self, remote: str = 'origin', prune: bool = True) -> OperationResult:
        """Fetch from a remote, optionally pruning deleted upstream refs."""
        try:
            self._repo.remotes[remote].fetch(prune=prune)
            return OperationResult(True, OperationType.FETCH, f"Fetched from {remote}")
        except GitCommandError as e:
            return OperationResult(False, OperationType.FETCH, "Fetch failed", e)

    def checkout(self, branch: str) -> OperationResult:
        """Check out a local branch by name."""
        try:
            self._repo.git.checkout(branch)
            return OperationResult(True, OperationType.CHECKOUT, f"Checked out {branch}")
        except GitCommandError as e:
            return OperationResult(False, OperationType.CHECKOUT, "Checkout failed", e)

    def pull(self, remote: str, branch: str, rebase: bool = False) -> OperationResult:
        """Pull from remote/branch, using rebase or merge. Aborts on failure."""
        op_type = OperationType.REBASE if rebase else OperationType.PULL
        try:
            if rebase:
                self._repo.git.pull('--rebase', remote, branch)
            else:
                self._repo.git.pull(remote, branch)
            return OperationResult(True, op_type, f"Pulled from {remote}/{branch}")
        except GitCommandError as e:
            try:
                if rebase:
                    self._repo.git.rebase('--abort')
                else:
                    self._repo.git.merge('--abort')
            except GitCommandError:
                pass
            return OperationResult(False, op_type, "Pull failed", e)

    def create_branch(self, name: str, start_point: str) -> OperationResult:
        """Create and check out a new branch from the given start point."""
        try:
            self._repo.git.checkout('-b', name, start_point)
            return OperationResult(True, OperationType.BRANCH_CREATE, f"Created branch {name}")
        except GitCommandError as e:
            return OperationResult(False, OperationType.BRANCH_CREATE, "Branch creation failed", e)

    def delete_branch(self, name: str, force: bool = False) -> OperationResult:
        """Delete a local branch. Use force=True for unmerged branches."""
        try:
            flag = '-D' if force else '-d'
            self._repo.git.branch(flag, name)
            return OperationResult(True, OperationType.BRANCH_DELETE, f"Deleted branch {name}")
        except GitCommandError as e:
            return OperationResult(False, OperationType.BRANCH_DELETE, "Branch deletion failed", e)

    def stash_push(self, message: str, include_untracked: bool = True) -> OperationResult:
        """Stash working tree changes with a descriptive message."""
        try:
            args = ['push', '-m', message]
            if include_untracked:
                args.insert(1, '-u')
            self._repo.git.stash(*args)
            return OperationResult(True, OperationType.STASH, f"Stashed changes: {message}")
        except GitCommandError as e:
            return OperationResult(False, OperationType.STASH, "Stash failed", e)

    def stash_pop(self) -> OperationResult:
        """Pop the most recent stash entry and apply it."""
        try:
            self._repo.git.stash('pop')
            return OperationResult(True, OperationType.STASH, "Popped stash")
        except GitCommandError as e:
            return OperationResult(False, OperationType.STASH, "Stash pop failed", e)

    def get_local_branches(self) -> list[BranchInfo]:
        """Return info for all local branches, including tracking config."""
        branches = []
        for branch in self._repo.heads:
            tracking = None
            with contextlib.suppress(GitCommandError):
                tracking = self._repo.git.rev_parse('--abbrev-ref', f'{branch.name}@{{upstream}}')

            has_tracking_config = False
            try:
                remote_cfg = self._repo.git.config('--get', f'branch.{branch.name}.remote')
                has_tracking_config = bool(remote_cfg.strip())
            except GitCommandError:
                pass

            branches.append(BranchInfo(
                name=branch.name,
                is_remote=False,
                commit_hash=branch.commit.hexsha,
                tracking_branch=tracking,
                has_tracking_config=has_tracking_config,
            ))
        return branches

    def get_remote_branches(self, remote: str = 'origin') -> list[BranchInfo]:
        """Return info for all branches on the given remote."""
        branches = []
        if remote not in self._repo.remotes:
            return branches

        for ref in self._repo.remotes[remote].refs:
            if ref.name == f'{remote}/HEAD':
                continue
            parts = ref.name.split('/', 1)
            if len(parts) < 2:
                continue
            branch_name = parts[1]
            branches.append(BranchInfo(
                name=branch_name,
                is_remote=True,
                remote_name=remote,
                commit_hash=ref.commit.hexsha
            ))
        return branches

    def get_branch_status(self, branch: str) -> BranchStatus:
        """Compare a local branch against its upstream (ahead/behind counts)."""
        status = BranchStatus()
        try:
            self._repo.git.rev_parse('--verify', branch)
            status.exists = True
            status.local_commit = self._repo.git.rev_parse(branch)

            try:
                self._repo.git.rev_parse('--abbrev-ref', f'{branch}@{{upstream}}')
                status.has_upstream = True
                status.remote_commit = self._repo.git.rev_parse(f'{branch}@{{u}}')

                status.commits_ahead = int(
                    self._repo.git.rev_list('--count', f'{branch}@{{u}}..{branch}')
                )
                status.commits_behind = int(
                    self._repo.git.rev_list('--count', f'{branch}..{branch}@{{u}}')
                )

                if status.commits_ahead > 0 and status.commits_behind > 0:
                    status.is_diverged = True
            except GitCommandError:
                pass
        except GitCommandError:
            pass

        return status

    def is_clean(self) -> bool:
        """Return True if the working tree has no staged, unstaged, or untracked changes."""
        return not self._repo.is_dirty(untracked_files=True)

    def get_change_counts(self) -> dict[str, int]:
        """Return counts of staged, unstaged, and untracked changes."""
        try:
            staged = len(self._repo.index.diff('HEAD'))
        except Exception:
            staged = 0
        unstaged = len(self._repo.index.diff(None))
        untracked = len(self._repo.untracked_files)
        return {'staged': staged, 'unstaged': unstaged, 'untracked': untracked}
