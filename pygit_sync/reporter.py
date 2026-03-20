"""SummaryReporter: generates and displays the final report."""

from __future__ import annotations

from pygit_sync.models import IssueType, SyncConfig, SyncIssue, SyncResult
from pygit_sync.output import SECTION_WIDTH
from pygit_sync.protocols import OutputHandler


class SummaryReporter:
    """Generates and displays summary reports"""

    def __init__(self, output: OutputHandler, plain: bool = False):
        """Create a reporter that writes to the given output handler."""
        self.output = output
        self.plain = plain

    def _e(self, emoji: str, plain: str) -> str:
        """Return *emoji* normally, or *plain* when --plain is active."""
        return plain if self.plain else emoji

    def print_summary(self, result: SyncResult, config: SyncConfig):
        """Print the final summary report with categorized issues and recommendations."""
        self.output.info("")
        if self.plain:
            self.output.info("+" + "=" * SECTION_WIDTH + "+")
            self.output.info("|" + "SUMMARY REPORT".center(SECTION_WIDTH) + "|")
            self.output.info("+" + "=" * SECTION_WIDTH + "+")
        else:
            self.output.info("\u2554" + "=" * SECTION_WIDTH + "\u2557")
            self.output.info("\u2551" + "SUMMARY REPORT".center(SECTION_WIDTH) + "\u2551")
            self.output.info("\u255a" + "=" * SECTION_WIDTH + "\u255d")
        self.output.info("")
        self.output.info(f"Total repositories processed: {result.repos_processed}")
        self.output.info("")

        if result.has_issues():
            self._print_issues_summary(result, config)
        else:
            self._print_success_summary(result, config)

        self.output.info("")
        self.output.info("=" * SECTION_WIDTH)

    def _print_issues_summary(self, result: SyncResult, config: SyncConfig):
        """Print all issue categories and actionable recommendations."""
        self.output.warning(f"{self._e(chr(0x26a0) + chr(0xfe0f), '[!]')}  ATTENTION REQUIRED")
        self.output.info("")

        self._print_issue_category(f"{self._e(chr(0x1f534), '[X]')} FAILED OPERATIONS",
                                   result.get_issues_by_type(IssueType.FAILED))
        self._print_issue_category(f"{self._e(chr(0x1f4a5), '[!]')} STASH CONFLICTS",
                                   result.get_issues_by_type(IssueType.STASH_CONFLICT))
        self._print_issue_category(f"{self._e(chr(0x1f500), '[~]')} DIVERGED BRANCHES",
                                   result.get_issues_by_type(IssueType.DIVERGED))
        self._print_issue_category(f"{self._e(chr(0x1f4dd), '[*]')} LOCAL CHANGES",
                                   result.get_issues_by_type(IssueType.LOCAL_CHANGES))
        self._print_issue_category(f"{self._e(chr(0x2b06) + chr(0xfe0f), '[^]')}  UNPUSHED COMMITS",
                                   result.get_issues_by_type(IssueType.UNPUSHED))
        self._print_issue_category(f"{self._e(chr(0x1f5d1) + chr(0xfe0f), '[-]')}  STALE BRANCHES",
                                   result.get_issues_by_type(IssueType.STALE))

        self.output.info("=" * SECTION_WIDTH)
        self.output.info("")
        self.output.info(f"{self._e(chr(0x1f4a1), '[i]')} RECOMMENDATIONS:")
        self.output.info("")

        if result.get_issues_by_type(IssueType.STASH_CONFLICT):
            self.output.error(f"{self._e(chr(0x1f6a8), '>>')} PRIORITY: Resolve stash conflicts first")
            self.output.info("")

        if result.get_issues_by_type(IssueType.LOCAL_CHANGES) and not config.stash_and_pull:
            self.output.info(f"{self._e(chr(0x2022), '-')} Use --stash-and-pull for repos with local changes")

        if result.get_issues_by_type(IssueType.DIVERGED):
            self.output.info(f"{self._e(chr(0x2022), '-')} Diverged branches need manual resolution:")
            for issue in result.get_issues_by_type(IssueType.DIVERGED):
                self.output.info(f"    cd '{issue.repo_path}' && git checkout {issue.branch}")
                self.output.info(f"      {self._e(chr(0x2022), '-')} Rebase: git rebase {config.remote_name}/{issue.branch}")
                self.output.info(f"      {self._e(chr(0x2022), '-')} Merge:  git merge {config.remote_name}/{issue.branch}")
                self.output.info(f"      {self._e(chr(0x2022), '-')} Reset:  git reset --hard {config.remote_name}/{issue.branch}")

        if config.dry_run:
            self.output.info("")
            self.output.info(f"{self._e(chr(0x1f50d), '>')} This was a DRY RUN - use --execute to apply changes")

    def _print_success_summary(self, result: SyncResult, config: SyncConfig):
        """Print the all-clear message with branch creation/update counts."""
        if result.repos_processed == 0:
            self.output.info("No repositories to sync.")
            return
        self.output.success(f"{self._e(chr(0x2705), '[ok]')} ALL REPOSITORIES ARE IN SYNC!")
        self.output.info("")

        if config.dry_run:
            if result.branches_created:
                self.output.info(f"Would create {len(result.branches_created)} branch(es)")
            if result.branches_updated:
                self.output.info(f"Would update {len(result.branches_updated)} branch(es)")
            self.output.info("")
            self.output.info(f"{self._e(chr(0x1f50d), '>')} This was a DRY RUN - use --execute to apply changes")
        else:
            if result.branches_created:
                self.output.info(f"Created {len(result.branches_created)} branch(es)")
            if result.branches_updated:
                self.output.info(f"Updated {len(result.branches_updated)} branch(es)")

    def _print_issue_category(self, title: str, issues: list[SyncIssue]):
        """Print a single issue category with its title and per-repo details."""
        if not issues:
            return

        self.output.info(f"{title} ({len(issues)}):")
        self.output.info("-" * SECTION_WIDTH)
        for issue in issues:
            self.output.info(f"  {self._e(chr(0x1f4c1), '>')} {issue.repo_path}")
            if issue.branch:
                self.output.info(f"     {self._e(chr(0x1f33f), '-')} {issue.branch}: {issue.details}")
            else:
                self.output.info(f"     {self._e(chr(0x21b3), '-')} {issue.details}")
        self.output.info("")
