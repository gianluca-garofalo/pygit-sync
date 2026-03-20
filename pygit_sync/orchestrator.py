"""SyncOrchestrator: coordinates sync across multiple repositories."""

from __future__ import annotations

import concurrent.futures
import threading
from pathlib import Path

from git import InvalidGitRepositoryError
from tqdm import tqdm

from pygit_sync.models import IssueType, SyncConfig, SyncIssue, SyncResult
from pygit_sync.output import BufferedOutputHandler
from pygit_sync.protocols import OutputHandler, SyncHook
from pygit_sync.repository import GitPythonRepository
from pygit_sync.scanner import RepositoryScanner
from pygit_sync.synchronizer import BranchSynchronizer


class SyncOrchestrator:
    """Main orchestrator - coordinates all sync operations"""

    def __init__(
        self,
        config: SyncConfig,
        output: OutputHandler,
        hooks: list[SyncHook] = None
    ):
        """Create an orchestrator with the given config, output handler, and optional hooks."""
        self.config = config
        self.output = output
        self.hooks = hooks or []
        self.scanner = RepositoryScanner(config.exclude_patterns)

    def sync_all(self, search_dir: Path) -> SyncResult:
        """Discover repositories under search_dir and sync them all (sequential or parallel)."""
        repos = list(self.scanner.find_repositories(search_dir))

        if not repos:
            self.output.warning(f"No git repositories found in {search_dir}")
            return SyncResult()

        self.output.info(f"Found {len(repos)} repositories")

        if self.config.parallel:
            return self._sync_parallel(repos)
        else:
            return self._sync_sequential(repos)

    def _sync_sequential(self, repos: list[Path]) -> SyncResult:
        """Sync repositories one at a time with a progress bar."""
        combined_result = SyncResult()

        with tqdm(total=len(repos), desc="Syncing", unit="repo", disable=self.config.dry_run) as pbar:
            for repo_path in repos:
                pbar.set_postfix_str(repo_path.name, refresh=True)
                result = self._sync_single_repo(repo_path)
                self._merge_results(combined_result, result)
                pbar.update(1)

        return combined_result

    def _sync_parallel(self, repos: list[Path]) -> SyncResult:
        """Sync repositories concurrently with buffered output per thread."""
        combined_result = SyncResult()
        lock = threading.Lock()

        def _sync_with_buffer(repo_path: Path) -> tuple[SyncResult, BufferedOutputHandler]:
            buf = BufferedOutputHandler()
            result = self._sync_single_repo(repo_path, output_override=buf)
            return result, buf

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            futures = {executor.submit(_sync_with_buffer, repo): repo for repo in repos}

            with tqdm(total=len(repos), desc="Syncing repositories") as pbar:
                for future in concurrent.futures.as_completed(futures):
                    repo_path = futures[future]
                    try:
                        result, buf = future.result()
                        with lock:
                            buf.flush_to(self.output)
                            self._merge_results(combined_result, result)
                    except Exception as e:
                        self.output.error(f"Error syncing {repo_path}: {e}")
                        with lock:
                            combined_result.add_issue(SyncIssue(
                                str(repo_path), "", IssueType.FAILED,
                                f"Unexpected error: {str(e)}"
                            ))
                    finally:
                        pbar.set_postfix_str(repo_path.name, refresh=True)
                        pbar.update(1)

        return combined_result

    def _sync_single_repo(self, repo_path: Path, output_override: OutputHandler = None) -> SyncResult:
        """Open a repository, run hooks, sync branches, and handle errors."""
        output = output_override or self.output
        repo = None
        try:
            repo = GitPythonRepository(repo_path)

            for hook in self.hooks:
                if not hook.before_sync(repo, self.config):
                    return SyncResult()

            output.section(f"Processing: {repo_path}")
            synchronizer = BranchSynchronizer(repo, output, self.config)
            result = synchronizer.sync()

            for hook in self.hooks:
                hook.after_sync(repo, result)

            return result

        except InvalidGitRepositoryError:
            output.error(f"Not a valid git repository: {repo_path}")
            result = SyncResult()
            result.add_issue(SyncIssue(
                str(repo_path), "", IssueType.FAILED,
                "Invalid git repository"
            ))
            return result
        except Exception as e:
            output.error(f"Unexpected error in {repo_path}: {e}")
            if repo is not None:
                for hook in self.hooks:
                    hook.on_error(repo, e)

            result = SyncResult()
            result.add_issue(SyncIssue(
                str(repo_path), "", IssueType.FAILED,
                f"Unexpected error: {str(e)}"
            ))
            return result
        finally:
            if repo is not None:
                repo.close()

    def _merge_results(self, combined: SyncResult, new: SyncResult):
        """Accumulate counts and issues from a single repo into the combined result."""
        combined.repos_processed += new.repos_processed
        combined.branches_created.extend(new.branches_created)
        combined.branches_updated.extend(new.branches_updated)
        combined.issues.extend(new.issues)
