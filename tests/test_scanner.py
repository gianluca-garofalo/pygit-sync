"""Tests for RepositoryScanner."""

from pathlib import Path

from pygit_sync import RepositoryScanner


class TestRepositoryScanner:
    def test_find_repositories(self, tmp_path: Path):
        # Create fake git repos
        (tmp_path / "repo1" / ".git").mkdir(parents=True)
        (tmp_path / "repo2" / ".git").mkdir(parents=True)
        (tmp_path / "not-a-repo").mkdir(parents=True)

        scanner = RepositoryScanner()
        repos = list(scanner.find_repositories(tmp_path))
        repo_names = {r.name for r in repos}
        assert "repo1" in repo_names
        assert "repo2" in repo_names
        assert "not-a-repo" not in repo_names

    def test_find_nested_repositories(self, tmp_path: Path):
        (tmp_path / "parent" / "child" / ".git").mkdir(parents=True)
        scanner = RepositoryScanner()
        repos = list(scanner.find_repositories(tmp_path))
        assert len(repos) == 1
        assert repos[0].name == "child"

    def test_exclude_patterns(self, tmp_path: Path):
        (tmp_path / "repo1" / ".git").mkdir(parents=True)
        (tmp_path / "node_modules" / "dep" / ".git").mkdir(parents=True)

        scanner = RepositoryScanner(exclude_patterns=["node_modules"])
        repos = list(scanner.find_repositories(tmp_path))
        assert len(repos) == 1
        assert repos[0].name == "repo1"

    def test_no_repos_found(self, tmp_path: Path):
        scanner = RepositoryScanner()
        repos = list(scanner.find_repositories(tmp_path))
        assert repos == []

    def test_git_file_not_dir_skipped(self, tmp_path: Path):
        # .git as a file (submodule style) should be skipped
        repo_dir = tmp_path / "sub"
        repo_dir.mkdir()
        (repo_dir / ".git").write_text("gitdir: ../somewhere")

        scanner = RepositoryScanner()
        repos = list(scanner.find_repositories(tmp_path))
        assert repos == []

    def test_symlink_not_followed(self, tmp_path: Path):
        """Symlinks should not be followed to avoid loops and directory escape."""
        # Create a real repo
        (tmp_path / "real_repo" / ".git").mkdir(parents=True)
        # Create a symlink to the real repo
        link_dir = tmp_path / "linked"
        link_dir.mkdir()
        (link_dir / "symlinked_repo").symlink_to(tmp_path / "real_repo")

        scanner = RepositoryScanner()
        repos = list(scanner.find_repositories(tmp_path))
        # Should only find the real repo, not traverse the symlink
        assert len(repos) == 1
        assert repos[0].name == "real_repo"

    def test_deduplication_via_resolve(self, tmp_path: Path):
        """Same repo reachable via different paths should only appear once."""
        (tmp_path / "repos" / "myrepo" / ".git").mkdir(parents=True)

        scanner = RepositoryScanner()
        repos = list(scanner.find_repositories(tmp_path))
        assert len(repos) == 1

    def test_exclude_prunes_traversal(self, tmp_path: Path):
        """Excluded directories should not be descended into."""
        (tmp_path / "vendor" / "dep1" / ".git").mkdir(parents=True)
        (tmp_path / "vendor" / "dep2" / ".git").mkdir(parents=True)
        (tmp_path / "myrepo" / ".git").mkdir(parents=True)

        scanner = RepositoryScanner(exclude_patterns=["vendor"])
        repos = list(scanner.find_repositories(tmp_path))
        assert len(repos) == 1
        assert repos[0].name == "myrepo"
