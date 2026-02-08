"""Tests for domain models (dataclasses, enums)."""

from datetime import datetime
from pathlib import Path

from pygit_sync import (
    BranchInfo,
    BranchStatus,
    IssueType,
    OperationResult,
    OperationType,
    SyncConfig,
    SyncIssue,
    SyncResult,
    load_config_file,
)


class TestBranchInfo:
    def test_local_branch_full_name(self):
        branch = BranchInfo(name="main", is_remote=False)
        assert branch.full_name == "main"

    def test_remote_branch_full_name(self):
        branch = BranchInfo(name="main", is_remote=True, remote_name="origin")
        assert branch.full_name == "origin/main"

    def test_remote_branch_without_remote_name(self):
        branch = BranchInfo(name="main", is_remote=True)
        assert branch.full_name == "main"

    def test_frozen(self):
        branch = BranchInfo(name="main", is_remote=False)
        try:
            branch.name = "other"
            raise AssertionError("Should have raised FrozenInstanceError")
        except AttributeError:
            pass


class TestBranchStatus:
    def test_defaults(self):
        status = BranchStatus()
        assert status.exists is False
        assert status.is_clean is False
        assert status.has_upstream is False
        assert status.commits_ahead == 0
        assert status.commits_behind == 0
        assert status.is_diverged is False
        assert status.local_commit is None
        assert status.remote_commit is None

    def test_mutable(self):
        status = BranchStatus()
        status.exists = True
        status.commits_ahead = 3
        assert status.exists is True
        assert status.commits_ahead == 3


class TestSyncIssue:
    def test_str_representation(self):
        issue = SyncIssue(
            repo_path="/tmp/repo",
            branch="main",
            issue_type=IssueType.FAILED,
            details="something broke",
        )
        text = str(issue)
        assert "/tmp/repo" in text
        assert "main" in text
        assert "something broke" in text

    def test_timestamp_auto_set(self):
        before = datetime.now()
        issue = SyncIssue(
            repo_path="/tmp/repo",
            branch="main",
            issue_type=IssueType.FAILED,
            details="error",
        )
        after = datetime.now()
        assert before <= issue.timestamp <= after


class TestOperationResult:
    def test_success_result(self):
        result = OperationResult(True, OperationType.FETCH, "OK")
        assert result.success is True
        assert result.error is None

    def test_failure_result(self):
        err = RuntimeError("fail")
        result = OperationResult(False, OperationType.FETCH, "Failed", err)
        assert result.success is False
        assert result.error is err


class TestSyncResult:
    def test_empty(self):
        result = SyncResult()
        assert result.repos_processed == 0
        assert result.has_issues() is False
        assert result.has_critical_issues() is False

    def test_add_issue(self):
        result = SyncResult()
        issue = SyncIssue("/tmp/repo", "main", IssueType.UNPUSHED, "2 commits ahead")
        result.add_issue(issue)
        assert result.has_issues() is True
        assert result.has_critical_issues() is False

    def test_critical_issues(self):
        result = SyncResult()
        result.add_issue(SyncIssue("/tmp/repo", "main", IssueType.FAILED, "error"))
        assert result.has_critical_issues() is True

    def test_get_issues_by_type(self):
        result = SyncResult()
        result.add_issue(SyncIssue("/tmp/r1", "main", IssueType.FAILED, "err"))
        result.add_issue(SyncIssue("/tmp/r2", "dev", IssueType.UNPUSHED, "ahead"))
        result.add_issue(SyncIssue("/tmp/r3", "feat", IssueType.FAILED, "err2"))
        failed = result.get_issues_by_type(IssueType.FAILED)
        assert len(failed) == 2
        unpushed = result.get_issues_by_type(IssueType.UNPUSHED)
        assert len(unpushed) == 1


class TestSyncResultToDict:
    def test_empty_result(self):
        result = SyncResult()
        d = result.to_dict()
        assert d['repos_processed'] == 0
        assert d['branches_created'] == []
        assert d['branches_updated'] == []
        assert d['issues'] == []
        assert d['has_critical_issues'] is False

    def test_with_data(self):
        result = SyncResult()
        result.repos_processed = 2
        result.branches_created.append(('/tmp/repo', 'feat'))
        result.branches_updated.append(('/tmp/repo', 'main'))
        result.add_issue(SyncIssue('/tmp/repo', 'main', IssueType.FAILED, 'error'))
        d = result.to_dict()
        assert d['repos_processed'] == 2
        assert len(d['branches_created']) == 1
        assert d['branches_created'][0] == {'repo': '/tmp/repo', 'branch': 'feat'}
        assert len(d['branches_updated']) == 1
        assert len(d['issues']) == 1
        assert d['issues'][0]['type'] == 'FAILED'
        assert d['issues'][0]['branch'] == 'main'
        assert 'timestamp' in d['issues'][0]
        assert d['has_critical_issues'] is True


class TestSyncConfig:
    def test_defaults(self):
        config = SyncConfig()
        assert config.dry_run is True
        assert config.use_rebase is True
        assert config.remove_stale is True
        assert config.stash_and_pull is False
        assert config.parallel is False
        assert config.verbose is False
        assert config.exclude_patterns == []
        assert config.remote_name == 'origin'
        assert config.branch_patterns == []
        assert config.json_output is False
        assert config.fetch_retries == 0

    def test_with_updates(self):
        config = SyncConfig()
        updated = config.with_updates(dry_run=False, parallel=True)
        assert updated.dry_run is False
        assert updated.parallel is True
        # Original unchanged
        assert config.dry_run is True
        assert config.parallel is False

    def test_with_updates_new_fields(self):
        config = SyncConfig()
        updated = config.with_updates(
            remote_name='upstream',
            branch_patterns=['main', 'develop'],
            json_output=True,
            fetch_retries=3,
        )
        assert updated.remote_name == 'upstream'
        assert updated.branch_patterns == ['main', 'develop']
        assert updated.json_output is True
        assert updated.fetch_retries == 3
        # Original unchanged
        assert config.remote_name == 'origin'
        assert config.branch_patterns == []


class TestLoadConfigFile:
    def test_no_config_returns_empty(self, tmp_path: Path):
        result = load_config_file(tmp_path)
        assert result == {}

    def test_loads_from_search_dir(self, tmp_path: Path):
        config_file = tmp_path / '.pygitrc.toml'
        config_file.write_text('parallel = true\nremote_name = "upstream"\n')
        result = load_config_file(tmp_path)
        assert result.get('parallel') is True
        assert result.get('remote_name') == 'upstream'

    def test_explicit_path(self, tmp_path: Path):
        config_file = tmp_path / 'custom.toml'
        config_file.write_text('verbose = true\n')
        result = load_config_file(tmp_path, config_path=str(config_file))
        assert result.get('verbose') is True

    def test_explicit_path_not_found(self, tmp_path: Path, capsys):
        result = load_config_file(tmp_path, config_path='/nonexistent/config.toml')
        assert result == {}
        captured = capsys.readouterr()
        assert "not found" in captured.out

    def test_malformed_toml(self, tmp_path: Path, capsys):
        config_file = tmp_path / '.pygitrc.toml'
        config_file.write_text('this is not valid [[[ toml ===')
        result = load_config_file(tmp_path)
        assert result == {}
        captured = capsys.readouterr()
        assert "Failed to parse" in captured.out
