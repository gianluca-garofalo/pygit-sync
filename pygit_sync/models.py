"""Domain models: enums, dataclasses, and configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any


class IssueType(Enum):
    """Type-safe issue categories"""
    FAILED = auto()
    STASH_CONFLICT = auto()
    DIVERGED = auto()
    LOCAL_CHANGES = auto()
    UNPUSHED = auto()
    STALE = auto()


class OperationType(Enum):
    """Types of git operations"""
    FETCH = auto()
    CHECKOUT = auto()
    PULL = auto()
    REBASE = auto()
    MERGE = auto()
    STASH = auto()
    BRANCH_CREATE = auto()
    BRANCH_DELETE = auto()


@dataclass(frozen=True)
class BranchInfo:
    """Information about a git branch"""
    name: str
    is_remote: bool
    remote_name: str | None = None
    commit_hash: str | None = None
    tracking_branch: str | None = None
    has_tracking_config: bool = False

    @property
    def full_name(self) -> str:
        """Return the fully qualified branch name (e.g. 'origin/main' for remote branches)."""
        if self.is_remote and self.remote_name:
            return f"{self.remote_name}/{self.name}"
        return self.name


@dataclass(frozen=True)
class SyncIssue:
    """Immutable issue record"""
    repo_path: str
    branch: str
    issue_type: IssueType
    details: str
    timestamp: datetime = field(default_factory=datetime.now)

    def __str__(self) -> str:
        return f"[{self.timestamp:%H:%M:%S}] {self.repo_path} / {self.branch}: {self.details}"


@dataclass
class BranchStatus:
    """Status of a branch relative to its upstream"""
    exists: bool = False
    is_clean: bool = False
    has_upstream: bool = False
    commits_ahead: int = 0
    commits_behind: int = 0
    is_diverged: bool = False
    local_commit: str | None = None
    remote_commit: str | None = None


@dataclass(frozen=True)
class OperationResult:
    """Result of a single git operation"""
    success: bool
    operation: OperationType
    message: str
    error: Exception | None = None


@dataclass
class SyncResult:
    """Mutable result accumulator"""
    repos_processed: int = 0
    branches_created: list[tuple[str, str]] = field(default_factory=list)
    branches_updated: list[tuple[str, str]] = field(default_factory=list)
    issues: list[SyncIssue] = field(default_factory=list)

    def add_issue(self, issue: SyncIssue) -> None:
        """Record a sync issue encountered during processing."""
        self.issues.append(issue)

    def get_issues_by_type(self, issue_type: IssueType) -> list[SyncIssue]:
        """Filter issues by category (e.g. FAILED, DIVERGED)."""
        return [issue for issue in self.issues if issue.issue_type == issue_type]

    def has_issues(self) -> bool:
        """Return True if any issues were recorded."""
        return len(self.issues) > 0

    def has_critical_issues(self) -> bool:
        """Return True if any FAILED, STASH_CONFLICT, or DIVERGED issues exist."""
        critical_types = {IssueType.FAILED, IssueType.STASH_CONFLICT, IssueType.DIVERGED}
        return any(issue.issue_type in critical_types for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON output."""
        return {
            'repos_processed': self.repos_processed,
            'branches_created': [{'repo': r, 'branch': b} for r, b in self.branches_created],
            'branches_updated': [{'repo': r, 'branch': b} for r, b in self.branches_updated],
            'issues': [
                {
                    'repo_path': i.repo_path,
                    'branch': i.branch,
                    'type': i.issue_type.name,
                    'details': i.details,
                    'timestamp': i.timestamp.isoformat(),
                }
                for i in self.issues
            ],
            'has_critical_issues': self.has_critical_issues(),
        }


@dataclass(frozen=True)
class SyncConfig:
    """Configuration for sync operations"""
    dry_run: bool = True
    use_rebase: bool = True
    remove_stale: bool = True
    stash_and_pull: bool = False
    parallel: bool = False
    max_workers: int = field(default_factory=lambda: min(os.cpu_count() or 4, 8))
    verbose: bool = False
    exclude_patterns: list[str] = field(default_factory=list)
    remote_name: str = 'origin'
    branch_patterns: list[str] = field(default_factory=list)
    json_output: bool = False
    fetch_retries: int = 0

    def with_updates(self, **kwargs) -> SyncConfig:
        """Return a new SyncConfig with the given fields replaced."""
        current = {f.name: getattr(self, f.name) for f in self.__dataclass_fields__.values()}
        current.update(kwargs)
        return SyncConfig(**current)
