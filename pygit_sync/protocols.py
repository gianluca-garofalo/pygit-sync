"""Protocols and abstract interfaces for dependency injection."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Protocol

from pygit_sync.models import (
    BranchInfo,
    BranchStatus,
    OperationResult,
    SyncConfig,
    SyncResult,
)


class GitRepository(Protocol):
    """Protocol for git repository operations"""

    def fetch(self, remote: str = 'origin', prune: bool = True) -> OperationResult: ...
    def checkout(self, branch: str) -> OperationResult: ...
    def pull(self, remote: str, branch: str, rebase: bool = False) -> OperationResult: ...
    def create_branch(self, name: str, start_point: str) -> OperationResult: ...
    def delete_branch(self, name: str, force: bool = False) -> OperationResult: ...
    def stash_push(self, message: str, include_untracked: bool = True) -> OperationResult: ...
    def stash_pop(self) -> OperationResult: ...
    def get_local_branches(self) -> list[BranchInfo]: ...
    def get_remote_branches(self, remote: str = 'origin') -> list[BranchInfo]: ...
    def get_branch_status(self, branch: str) -> BranchStatus: ...
    def is_clean(self) -> bool: ...
    def get_change_counts(self) -> dict[str, int]: ...

    @property
    def path(self) -> Path: ...

    @property
    def current_branch(self) -> str | None: ...


class OutputHandler(Protocol):
    """Protocol for handling output"""

    def info(self, message: str, indent: int = 0) -> None: ...
    def success(self, message: str, indent: int = 0) -> None: ...
    def warning(self, message: str, indent: int = 0) -> None: ...
    def error(self, message: str, indent: int = 0) -> None: ...
    def section(self, title: str) -> None: ...
    def debug(self, message: str) -> None: ...


class SyncHook(ABC):
    """Abstract base class for sync hooks (plugin architecture)"""

    @abstractmethod
    def before_sync(self, repo: GitRepository, config: SyncConfig) -> bool:
        """Called before syncing. Return False to skip this repo."""
        pass

    @abstractmethod
    def after_sync(self, repo: GitRepository, result: SyncResult) -> None:
        """Called after syncing a repository with its result."""
        pass

    @abstractmethod
    def on_error(self, repo: GitRepository, error: Exception) -> None:
        """Called when an unhandled error occurs during sync."""
        pass
