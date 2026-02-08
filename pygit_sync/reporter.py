"""SummaryReporter: generates and displays the final report."""

from __future__ import annotations

from pygit_sync.models import IssueType, SyncConfig, SyncIssue, SyncResult
from pygit_sync.output import SECTION_WIDTH
from pygit_sync.protocols import OutputHandler


class SummaryReporter:
    """Generates and displays summary reports"""

    def __init__(self, output: OutputHandler):
        """Create a reporter that writes to the given output handler."""
        self.output = output

    def print_summary(self, result: SyncResult, config: SyncConfig):
        """Print the final summary report with categorized issues and recommendations."""
        self.output.section("\u2554" + "=" * SECTION_WIDTH + "\u2557")
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
        self.output.warning("\u26a0\ufe0f  ATTENTION REQUIRED")
        self.output.info("")

        self._print_issue_category("\U0001f534 FAILED OPERATIONS",
                                   result.get_issues_by_type(IssueType.FAILED))
        self._print_issue_category("\U0001f4a5 STASH CONFLICTS",
                                   result.get_issues_by_type(IssueType.STASH_CONFLICT))
        self._print_issue_category("\U0001f500 DIVERGED BRANCHES",
                                   result.get_issues_by_type(IssueType.DIVERGED))
        self._print_issue_category("\U0001f4dd LOCAL CHANGES",
                                   result.get_issues_by_type(IssueType.LOCAL_CHANGES))
        self._print_issue_category("\u2b06\ufe0f  UNPUSHED COMMITS",
                                   result.get_issues_by_type(IssueType.UNPUSHED))
        self._print_issue_category("\U0001f5d1\ufe0f  STALE BRANCHES",
                                   result.get_issues_by_type(IssueType.STALE))

        self.output.info("=" * SECTION_WIDTH)
        self.output.info("")
        self.output.info("\U0001f4a1 RECOMMENDATIONS:")
        self.output.info("")

        if result.get_issues_by_type(IssueType.STASH_CONFLICT):
            self.output.error("\U0001f6a8 PRIORITY: Resolve stash conflicts first")
            self.output.info("")

        if result.get_issues_by_type(IssueType.LOCAL_CHANGES) and not config.stash_and_pull:
            self.output.info("\u2022 Use --stash-and-pull for repos with local changes")

        if result.get_issues_by_type(IssueType.DIVERGED):
            self.output.info("\u2022 Diverged branches need manual resolution")

        if config.dry_run:
            self.output.info("")
            self.output.info("\U0001f50d This was a DRY RUN - use --execute to apply changes")

    def _print_success_summary(self, result: SyncResult, config: SyncConfig):
        """Print the all-clear message with branch creation/update counts."""
        self.output.success("\u2705 ALL REPOSITORIES ARE IN SYNC!")
        self.output.info("")

        if config.dry_run:
            if result.branches_created:
                self.output.info(f"Would create {len(result.branches_created)} branch(es)")
            if result.branches_updated:
                self.output.info(f"Would update {len(result.branches_updated)} branch(es)")
            self.output.info("")
            self.output.info("\U0001f50d This was a DRY RUN - use --execute to apply changes")
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
            self.output.info(f"  \U0001f4c1 {issue.repo_path}")
            if issue.branch:
                self.output.info(f"     \U0001f33f {issue.branch}: {issue.details}")
            else:
                self.output.info(f"     \u21b3 {issue.details}")
        self.output.info("")
