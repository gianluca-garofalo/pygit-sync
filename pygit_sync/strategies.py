"""Branch sync strategies: one class per branch state."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from pygit_sync.models import (
    BranchInfo,
    BranchStatus,
    IssueType,
    SyncConfig,
    SyncIssue,
)
from pygit_sync.output import SECTION_WIDTH
from pygit_sync.protocols import GitRepository, OutputHandler


class BranchSyncStrategy(ABC):
    """Abstract strategy for syncing branches."""

    def __init__(self, repo: GitRepository, output: OutputHandler, config: SyncConfig):
        """Initialize with a repository, output handler, and sync configuration."""
        self.repo = repo
        self.output = output
        self.config = config

    @abstractmethod
    def can_handle(self, branch_info: BranchInfo, status: BranchStatus) -> bool:
        """Return True if this strategy applies to the given branch state."""
        pass

    @abstractmethod
    def sync(self, branch_info: BranchInfo, remote_name: str, status: BranchStatus) -> SyncIssue | None:
        """Sync the branch and return a SyncIssue if a problem was found, or None on success."""
        pass


class CleanFastForwardStrategy(BranchSyncStrategy):
    """Strategy for clean branches that can fast-forward."""

    def can_handle(self, branch_info: BranchInfo, status: BranchStatus) -> bool:
        """Match branches that are behind remote with a clean working tree."""
        return (
            status.exists and
            status.has_upstream and
            status.commits_ahead == 0 and
            status.commits_behind > 0 and
            self.repo.is_clean()
        )

    def sync(self, branch_info: BranchInfo, remote_name: str, status: BranchStatus) -> SyncIssue | None:
        """Pull (rebase or merge) to fast-forward the branch."""
        if self.config.dry_run:
            action = "rebase" if self.config.use_rebase else "pull"
            self.output.info(f"[DRY RUN] Would {action} {branch_info.name}", indent=1)
            return None

        result = self.repo.pull(remote_name, branch_info.name, self.config.use_rebase)
        if result.success:
            operation = "rebased" if self.config.use_rebase else "merged"
            self.output.success(f"\u2713 Successfully {operation}", indent=1)
            return None
        else:
            self.output.error(f"\u2717 Pull failed: {result.message}", indent=1)
            return SyncIssue(
                str(self.repo.path),
                branch_info.name,
                IssueType.FAILED,
                result.message
            )


class DirtyWorkingTreeStrategy(BranchSyncStrategy):
    """Strategy for branches with local changes."""

    def can_handle(self, branch_info: BranchInfo, status: BranchStatus) -> bool:
        """Match branches that are behind remote with uncommitted changes."""
        return (
            status.exists and
            status.has_upstream and
            status.commits_behind > 0 and
            not self.repo.is_clean()
        )

    def sync(self, branch_info: BranchInfo, remote_name: str, status: BranchStatus) -> SyncIssue | None:
        """Skip with warning, or stash-pull-pop if --stash-and-pull is enabled."""
        changes_desc = self._get_change_description()
        self.output.warning(f"Local changes detected: {changes_desc}", indent=1)

        if not self.config.stash_and_pull:
            self.output.warning("\u26a0 Skipping pull to avoid conflicts", indent=1)
            self._show_manual_instructions(branch_info)
            return SyncIssue(
                str(self.repo.path),
                branch_info.name,
                IssueType.LOCAL_CHANGES,
                changes_desc
            )

        return self._stash_pull_and_pop(branch_info, remote_name)

    def _get_change_description(self) -> str:
        """Build a human-readable summary of working tree changes."""
        counts = self.repo.get_change_counts()
        parts = []
        if counts['staged']:
            parts.append(f"{counts['staged']} staged")
        if counts['unstaged']:
            parts.append(f"{counts['unstaged']} modified")
        if counts['untracked']:
            parts.append(f"{counts['untracked']} untracked")
        return ', '.join(parts) if parts else 'uncommitted changes'

    def _show_manual_instructions(self, branch_info: BranchInfo):
        """Print step-by-step instructions for manually resolving dirty state."""
        self.output.info("")
        self.output.info("To update this branch, you can:", indent=1)
        self.output.info("  1. Commit changes: git add -A && git commit -m 'WIP'", indent=1)
        self.output.info("  2. Stash and pull: git stash && git pull && git stash pop", indent=1)
        self.output.info("  3. Use --stash-and-pull flag to automate", indent=1)

    def _stash_pull_and_pop(self, branch_info: BranchInfo, remote_name: str) -> SyncIssue | None:
        """Stash local changes, pull from remote, then reapply the stash."""
        if self.config.dry_run:
            self.output.info("[DRY RUN] Would stash, pull, and reapply", indent=1)
            return None

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        stash_msg = f"auto-stash-{timestamp}-{branch_info.name}"

        stash_result = self.repo.stash_push(stash_msg)
        if not stash_result.success:
            self.output.error(f"\u2717 Failed to stash: {stash_result.message}", indent=1)
            return SyncIssue(
                str(self.repo.path),
                branch_info.name,
                IssueType.FAILED,
                f"Stash failed: {stash_result.message}"
            )

        self.output.success(f"\u2713 Stashed changes: {stash_msg}", indent=1)

        pull_result = self.repo.pull(remote_name, branch_info.name, self.config.use_rebase)
        if not pull_result.success:
            self.output.error(f"\u2717 Pull failed: {pull_result.message}", indent=1)
            self.repo.stash_pop()
            return SyncIssue(
                str(self.repo.path),
                branch_info.name,
                IssueType.FAILED,
                f"Pull failed: {pull_result.message}"
            )

        operation = "rebased" if self.config.use_rebase else "merged"
        self.output.success(f"\u2713 Successfully {operation}", indent=1)

        self.output.info("Reapplying stashed changes...", indent=1)
        pop_result = self.repo.stash_pop()

        if pop_result.success:
            self.output.success("\u2713 Stash reapplied successfully", indent=1)
            return None
        else:
            self._show_stash_conflict_help(branch_info, stash_msg)
            return SyncIssue(
                str(self.repo.path),
                branch_info.name,
                IssueType.STASH_CONFLICT,
                f"stash: {stash_msg}"
            )

    def _show_stash_conflict_help(self, branch_info: BranchInfo, stash_msg: str):
        """Print conflict resolution instructions after a failed stash pop."""
        self.output.error("", indent=1)
        self.output.error("\u26a0\u26a0\u26a0 STASH CONFLICT DETECTED \u26a0\u26a0\u26a0", indent=1)
        self.output.info("\u2501" * SECTION_WIDTH, indent=1)
        self.output.info("The pull succeeded but stashed changes conflict.", indent=1)
        self.output.info("", indent=1)
        self.output.info("To resolve:", indent=1)
        self.output.info(f"  cd '{self.repo.path}'", indent=1)
        self.output.info("  git stash show -p stash@{0}", indent=1)
        self.output.info("  git stash apply stash@{0}", indent=1)
        self.output.info("  # Resolve conflicts, then:", indent=1)
        self.output.info("  git stash drop stash@{0}", indent=1)
        self.output.info("\u2501" * SECTION_WIDTH, indent=1)


class DivergedBranchStrategy(BranchSyncStrategy):
    """Strategy for diverged branches (ahead and behind remote)."""

    def can_handle(self, branch_info: BranchInfo, status: BranchStatus) -> bool:
        """Match branches that have both local and remote commits not in common."""
        return status.is_diverged

    def sync(self, branch_info: BranchInfo, remote_name: str, status: BranchStatus) -> SyncIssue | None:
        """Report divergence and request manual resolution."""
        self.output.warning("\u26a0 Branch has diverged", indent=1)
        self.output.info(
            f"  {status.commits_ahead} commits ahead, "
            f"{status.commits_behind} commits behind",
            indent=1
        )
        self.output.info("  Manual resolution required:", indent=1)
        self.output.info(f"  cd '{self.repo.path}' && git status", indent=1)

        return SyncIssue(
            str(self.repo.path),
            branch_info.name,
            IssueType.DIVERGED,
            f"{status.commits_ahead} ahead, {status.commits_behind} behind"
        )


class AheadOfRemoteStrategy(BranchSyncStrategy):
    """Strategy for branches ahead of remote (unpushed commits)."""

    def can_handle(self, branch_info: BranchInfo, status: BranchStatus) -> bool:
        """Match branches with unpushed commits and nothing to pull."""
        return (
            status.has_upstream and
            status.commits_ahead > 0 and
            status.commits_behind == 0
        )

    def sync(self, branch_info: BranchInfo, remote_name: str, status: BranchStatus) -> SyncIssue | None:
        """Report unpushed commits as an informational issue."""
        self.output.info(f"\u2139 Branch is ahead of remote ({status.commits_ahead} commits)", indent=1)
        return SyncIssue(
            str(self.repo.path),
            branch_info.name,
            IssueType.UNPUSHED,
            f"{status.commits_ahead} commits ahead"
        )


class UpToDateStrategy(BranchSyncStrategy):
    """Strategy for branches already up to date."""

    def can_handle(self, branch_info: BranchInfo, status: BranchStatus) -> bool:
        """Match branches with zero commits ahead or behind."""
        return (
            status.has_upstream and
            status.commits_ahead == 0 and
            status.commits_behind == 0
        )

    def sync(self, branch_info: BranchInfo, remote_name: str, status: BranchStatus) -> SyncIssue | None:
        """Confirm the branch is in sync (no-op)."""
        if self.repo.is_clean():
            self.output.info("\u2713 Already up to date", indent=1)
        else:
            self.output.info("\u2713 Already up to date (with local changes)", indent=1)
        return None
