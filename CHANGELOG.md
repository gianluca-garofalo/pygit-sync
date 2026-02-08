# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-02-08

### Added
- `--no-create-branches` flag to disable automatic local branch creation for remote-only branches
- `--max-branch-age` flag to only create branches with commits newer than N days (default: 180)
- `get_commit_date()` method on `GitRepository` protocol for branch age filtering
- Pre-stash at sync level: with `--stash-and-pull`, dirty changes are stashed once before syncing all branches (enables checkout to other branches), then restored after

### Changed
- Branch creation now uses `git branch --track` instead of `git checkout -b` (no checkout needed)
- Synchronizer only checks out branches that are behind remote (avoids unnecessary checkout failures)
- Checkout error messages now include the actual git error instead of a generic "Checkout failed"
- Scanner stops at git repository boundaries (does not descend into submodules or build deps)

### Fixed
- Summary report now shows branch names alongside repo paths for stale/failed branch issues
- Repos with hundreds of remote branches no longer produce thousands of failed branch-creation attempts

## [1.1.0] - 2025-02-08

### Added
- `--branches` flag to filter sync to specific branches using glob patterns (e.g., `main,release/*`)
- `--remote` flag to sync from a remote other than `origin` (e.g., `upstream`)
- `--json` flag for structured JSON output (enables CI/scripting integration)
- `--fetch-retries` flag with exponential backoff for transient network failures
- `--config` flag and `.pygitrc.toml` config file support (search dir or home dir)
- `BufferedOutputHandler` for parallel mode to prevent output interleaving
- Detailed change descriptions for dirty working trees (staged, modified, untracked counts)
- `has_tracking_config` field on `BranchInfo` for accurate stale detection after `fetch --prune`
- Progress detail in parallel mode (shows repo name in tqdm postfix)
- `SyncResult.to_dict()` for JSON serialization

### Changed
- Scanner rewritten to use `os.walk(followlinks=False)` for symlink safety and deduplication
- Split single-file `pygit_sync.py` into 12-module package (`pygit_sync/`)

## [1.0.0] - 2025-02-08

### Added
- Initial release
- Recursive git repository discovery under a directory
- Per-branch sync with 5 strategies: up-to-date, fast-forward, dirty working tree, ahead-of-remote, diverged
- `--execute` flag (dry-run by default)
- `--no-rebase` flag for merge-based pulls
- `--no-remove-stale` flag to keep stale branches
- `--stash-and-pull` flag for auto-stash workflow
- `--parallel` flag with configurable `--max-workers`
- `--exclude` pattern for skipping directories
- `--verbose` flag for debug output
- Stale branch detection and cleanup (only branches with prior tracking upstream)
- Summary report with categorized issues
- Protocol-based dependency injection (`GitRepository`, `OutputHandler`)
- Strategy pattern for branch sync logic
- Hook system (`SyncHook`) for plugin architecture
- Exit code 0 on success, 1 on critical issues, 130 on interrupt

### Fixed
- `BranchSyncStrategy.sync()` missing `status` parameter (NameError)
- `op_type` unbound in `pull()` exception handler
- `repo` unbound in `_sync_single_repo()` exception handler
- Bare `except:` clauses replaced with specific exception types
- Thread safety for parallel mode (added `threading.Lock`)
- `OutputHandler` protocol aligned with implementations (indent param, debug method)
- Resource cleanup for `GitPythonRepository` (added `close()`)
