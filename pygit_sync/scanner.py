"""Repository scanner: finds git repos under a directory."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path


class RepositoryScanner:
    """Responsible for finding git repositories"""

    def __init__(self, exclude_patterns: list[str] = None):
        """Create a scanner with optional substring-based exclude patterns."""
        self.exclude_patterns = exclude_patterns or []

    def find_repositories(self, search_dir: Path) -> Iterator[Path]:
        """Find all git repositories, respecting exclude patterns and symlink safety."""
        seen_real_paths: set[str] = set()
        for dirpath, dirnames, _filenames in os.walk(search_dir, followlinks=False):
            current = Path(dirpath)

            if self._should_exclude(current):
                dirnames.clear()
                continue

            if '.git' in dirnames:
                real_path = str(current.resolve())
                if real_path not in seen_real_paths:
                    seen_real_paths.add(real_path)
                    yield current
                dirnames.clear()

    def _should_exclude(self, repo_path: Path) -> bool:
        """Return True if any exclude pattern is a substring of the path."""
        path_str = str(repo_path)
        return any(pattern in path_str for pattern in self.exclude_patterns)
