"""BranchSynchronizer: syncs a single repository's branches."""

from __future__ import annotations

import fnmatch
import time

from pygit_sync.models import (
    BranchInfo,
    IssueType,
    OperationResult,
    OperationType,
    SyncConfig,
    SyncIssue,
    SyncResult,
)
from pygit_sync.protocols import GitRepository, OutputHandler
from pygit_sync.strategies import (
    AheadOfRemoteStrategy,
    BranchSyncStrategy,
    CleanFastForwardStrategy,
    DirtyWorkingTreeStrategy,
    DivergedBranchStrategy,
    UpToDateStrategy,
)


class BranchSynchronizer:
    """Responsible for synchronizing a single repository"""

    def __init__(
        self,
        repo: GitRepository,
        output: OutputHandler,
        config: SyncConfig
    ):
        """Create a synchronizer for a single repository."""
        self.repo = repo
        self.output = output
        self.config = config

        self.strategies: list[BranchSyncStrategy] = [
            UpToDateStrategy(repo, output, config),
            CleanFastForwardStrategy(repo, output, config),
            DirtyWorkingTreeStrategy(repo, output, config),
            AheadOfRemoteStrategy(repo, output, config),
            DivergedBranchStrategy(repo, output, config),
        ]

    def _matches_branch_filter(self, branch_name: str) -> bool:
        """Return True if the branch matches the configured glob patterns (or no filter is set)."""
        if not self.config.branch_patterns:
            return True
        return any(fnmatch.fnmatch(branch_name, p) for p in self.config.branch_patterns)

    def sync(self) -> SyncResult:
        """Fetch, detect stale branches, and sync each remote branch. Returns accumulated results."""
        result = SyncResult()

        self.output.info("Fetching from remote...")
        fetch_result = self._fetch_remote()
        if not fetch_result.success:
            result.add_issue(SyncIssue(
                str(self.repo.path), "", IssueType.FAILED,
                f"Fetch failed: {fetch_result.message}"
            ))
            return result

        local_branches = {b.name: b for b in self.repo.get_local_branches()}
        remote_branches = {b.name: b for b in self.repo.get_remote_branches(self.config.remote_name)}

        if self.config.remove_stale:
            self._handle_stale_branches(local_branches, remote_branches, result)

        original_branch = self.repo.current_branch

        for branch_name, remote_branch in remote_branches.items():
            if not self._matches_branch_filter(branch_name):
                continue
            if branch_name in local_branches:
                issue = self._sync_existing_branch(local_branches[branch_name], remote_branch)
                if issue:
                    result.add_issue(issue)
                else:
                    result.branches_updated.append((str(self.repo.path), branch_name))
            else:
                if self._create_branch(remote_branch):
                    result.branches_created.append((str(self.repo.path), branch_name))
                else:
                    result.add_issue(SyncIssue(
                        str(self.repo.path), branch_name,
                        IssueType.FAILED, "Branch creation failed"
                    ))

        if original_branch and not self.config.dry_run:
            self.repo.checkout(original_branch)

        result.repos_processed = 1
        return result

    def _fetch_remote(self) -> OperationResult:
        """Fetch from remote with optional retry and exponential backoff."""
        if self.config.dry_run:
            self.output.info("[DRY RUN] Fetching remote (read-only) to analyze branches...", indent=1)
        max_attempts = 1 + self.config.fetch_retries
        result = OperationResult(False, OperationType.FETCH, "No fetch attempted")
        for attempt in range(max_attempts):
            result = self.repo.fetch(self.config.remote_name)
            if result.success:
                return result
            if attempt < max_attempts - 1:
                delay = 2 ** attempt
                self.output.warning(
                    f"Fetch failed, retrying in {delay}s... (attempt {attempt + 1}/{max_attempts})",
                    indent=1
                )
                time.sleep(delay)
        return result

    def _sync_existing_branch(
        self,
        local_branch: BranchInfo,
        remote_branch: BranchInfo
    ) -> SyncIssue | None:
        """Check out an existing branch, determine its status, and delegate to the matching strategy."""
        self.output.info(f"\u2713 Local branch exists: {local_branch.name}")

        if not self.config.dry_run:
            checkout_result = self.repo.checkout(local_branch.name)
            if not checkout_result.success:
                return SyncIssue(
                    str(self.repo.path), local_branch.name,
                    IssueType.FAILED, f"Checkout failed: {checkout_result.message}"
                )

        status = self.repo.get_branch_status(local_branch.name)

        for strategy in self.strategies:
            if strategy.can_handle(local_branch, status):
                return strategy.sync(local_branch, self.config.remote_name, status)

        return None

    def _create_branch(self, remote_branch: BranchInfo) -> bool:
        """Create a new local branch tracking the remote. Returns True on success."""
        self.output.info(f"Creating local branch: {remote_branch.name}")

        if self.config.dry_run:
            self.output.info(
                f"[DRY RUN] Would create: {remote_branch.name} from {remote_branch.full_name}",
                indent=1
            )
            return True

        result = self.repo.create_branch(remote_branch.name, remote_branch.full_name)
        if result.success:
            self.output.success(f"\u2713 Created: {remote_branch.name}", indent=1)
            return True
        else:
            self.output.error(f"\u2717 Failed to create: {remote_branch.name}", indent=1)
            return False

    def _handle_stale_branches(
        self,
        local_branches: dict[str, BranchInfo],
        remote_branches: dict[str, BranchInfo],
        result: SyncResult
    ):
        """Delete local branches whose upstream was removed. Skips local-only branches."""
        self.output.section("Checking for stale branches")

        current = self.repo.current_branch
        stale_found = False

        for branch_name, branch_info in local_branches.items():
            if not self._matches_branch_filter(branch_name):
                continue
            if branch_name not in remote_branches:
                stale_found = True

                if branch_name == current:
                    self.output.warning(
                        f"\u26a0 Skipping stale branch '{branch_name}' (currently checked out)"
                    )
                    result.add_issue(SyncIssue(
                        str(self.repo.path), branch_name,
                        IssueType.STALE, "currently checked out - cannot delete"
                    ))
                    continue

                has_upstream = branch_info.tracking_branch is not None or branch_info.has_tracking_config

                if has_upstream:
                    self.output.warning(f"\u26a0 Stale branch: {branch_name} (upstream deleted)")
                    if self.config.dry_run:
                        self.output.info(f"[DRY RUN] Would delete: {branch_name}", indent=1)
                    else:
                        delete_result = self.repo.delete_branch(branch_name, force=True)
                        if delete_result.success:
                            self.output.success(f"\u2713 Deleted: {branch_name}", indent=1)
                        else:
                            self.output.error(f"\u2717 Failed to delete: {branch_name}", indent=1)

                    result.add_issue(SyncIssue(
                        str(self.repo.path), branch_name,
                        IssueType.STALE, "upstream deleted"
                    ))
                else:
                    self.output.info(f"\u2139 Local-only branch: {branch_name} (skipping)")

        if not stale_found:
            self.output.info("No stale branches found")
