# pygit-sync

A CLI tool that recursively finds every git repository under a directory and synchronizes each one with its remote. Designed for developers who work across many repositories simultaneously and want a single command to bring everything up to date.

## The Problem It Solves

If you have a workspace with 10, 50, or 100+ git repositories, keeping them all in sync means `cd`-ing into each one and running `git pull`. This tool automates that:

1. Recursively discovers all git repositories under a given directory
2. Fetches the latest remote state for each
3. For every remote branch, determines the right action (fast-forward, skip, warn) based on local state
4. Cleans up stale branches whose upstream was deleted
5. Reports a categorized summary of what happened and what needs manual attention

## Installation

```bash
# Clone or download the project
cd pygit-sync

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install the package
pip install -e .

# (Optional) Install dev dependencies for testing and linting
pip install -e ".[dev]"
```

This registers the `pygit-sync` command globally in your environment.

## Quick Start

```bash
# Preview what would happen (dry-run, the default)
pygit-sync ~/projects

# Actually execute the sync
pygit-sync ~/projects --execute

# Parallel sync for speed
pygit-sync ~/projects --execute --parallel

# Exclude directories
pygit-sync ~/projects --exclude node_modules --exclude .cache

# Use merge instead of rebase
pygit-sync ~/projects --execute --no-rebase

# Auto-stash dirty repos, pull, then reapply
pygit-sync ~/projects --execute --stash-and-pull

# Sync only specific branches
pygit-sync ~/projects --execute --branches "main,develop,release/*"

# Use a different remote
pygit-sync ~/projects --execute --remote upstream

# JSON output for scripting
pygit-sync ~/projects --json | python -m json.tool

# Retry flaky fetches
pygit-sync ~/projects --execute --fetch-retries 2
```

## How It Works

### Discovery Phase

`RepositoryScanner` walks the directory tree using `os.walk` with `followlinks=False`, yielding every directory that contains a `.git` subdirectory. Symlinks are not followed (preventing loops and directory escape), and discovered paths are deduplicated via `resolve()`. Exclude patterns are matched as substring checks against the full path, and excluded directories are pruned early to avoid unnecessary traversal.

### Per-Repository Sync

For each discovered repo, `BranchSynchronizer` does the following:

1. **Fetch** from the remote (always happens, even in dry-run, since fetch is read-only and needed for accurate analysis). Transient failures can be retried with `--fetch-retries`.
2. **Detect stale branches** -- local branches whose tracking upstream no longer exists on the remote. These are deleted (unless `--no-remove-stale` is set or the branch is currently checked out). Only branches that *had* a tracking upstream are considered stale -- purely local branches are never deleted.
3. **Sync each remote branch** by comparing it to the local state. The tool selects a strategy based on the branch's status:

| Local State | Strategy | Action |
|---|---|---|
| Up to date (0 ahead, 0 behind) | `UpToDateStrategy` | No-op, reports status |
| Behind remote, clean working tree | `CleanFastForwardStrategy` | `git pull --rebase` (or merge) |
| Behind remote, dirty working tree | `DirtyWorkingTreeStrategy` | Skip with warning, OR stash-pull-pop if `--stash-and-pull` |
| Ahead of remote (unpushed commits) | `AheadOfRemoteStrategy` | Skip, report as informational issue |
| Diverged (ahead AND behind) | `DivergedBranchStrategy` | Skip, report as critical issue requiring manual resolution |

4. **Create new branches** -- if a remote branch has no local counterpart, create one tracking it
5. **Restore original branch** -- after iterating, check out whichever branch was active before the sync

When `--branches` is set, only matching branches are synced and evaluated for staleness. Non-matching branches are left untouched.

### Parallel Mode

With `--parallel`, repositories are synced concurrently using `ThreadPoolExecutor`. Each repo gets its own `BufferedOutputHandler` to prevent output interleaving -- messages are collected per-repo and flushed atomically under a lock after each repo completes. The progress bar shows which repo just finished. Max worker count defaults to `min(cpu_count, 8)` and can be overridden with `--max-workers`.

### JSON Output

With `--json`, all console output is suppressed during processing. After the sync completes, a structured JSON object is printed containing repos processed, branches created/updated, issues found, and whether critical issues were detected. This enables integration with CI pipelines, dashboards, or wrapper scripts.

### Config File

Settings can be persisted in a `.pygitrc.toml` file placed in the search directory or home directory (search directory takes precedence). CLI flags always override file values. Example:

```toml
# All keys are optional. Shown here with their defaults.
execute = false           # same as --execute (dry-run when false)
use_rebase = true         # false = merge instead of rebase (--no-rebase)
remove_stale = true       # false = keep stale branches (--no-remove-stale)
stash_and_pull = false    # same as --stash-and-pull
parallel = false          # same as --parallel
max_workers = 8           # same as --max-workers
verbose = false           # same as --verbose
remote_name = "origin"    # same as --remote
branch_patterns = []      # same as --branches (list of glob patterns)
exclude_patterns = []     # same as --exclude (list of substring patterns)
json_output = false       # same as --json
fetch_retries = 0         # same as --fetch-retries
```

An explicit path can be specified with `--config /path/to/config.toml`. Requires Python 3.11+ (built-in `tomllib`) or the `tomli` package for older versions.

### Summary Report

After all repos are processed, `SummaryReporter` prints a categorized breakdown:
- Failed operations
- Stash conflicts
- Diverged branches
- Local changes preventing sync
- Unpushed commits
- Stale branches

The process exits with code 0 on success, 1 if any critical issues (FAILED, STASH_CONFLICT, DIVERGED) were found, and 130 on keyboard interrupt.

## CLI Reference

```
usage: pygit-sync [--version] [--execute] [--no-rebase]
                     [--no-remove-stale] [--stash-and-pull]
                     [--parallel] [--max-workers N]
                     [--exclude PATTERN] [--verbose]
                     [--remote NAME] [--branches PATTERNS]
                     [--json] [--fetch-retries N]
                     [--config PATH]
                     [directory]
```

| Flag | Default | Description |
|---|---|---|
| `directory` | `.` | Root directory to search for git repos |
| `--execute` | off (dry-run) | Actually perform sync operations |
| `--no-rebase` | rebase on | Use merge instead of rebase |
| `--no-remove-stale` | remove on | Keep stale local branches |
| `--stash-and-pull` | off | Auto-stash dirty trees, pull, then pop |
| `--parallel` | off | Sync repos concurrently |
| `--max-workers N` | min(cpu, 8) | Thread pool size for parallel mode |
| `--exclude PATTERN` | none | Substring exclude pattern (repeatable) |
| `--verbose` | off | Debug-level output and logging |
| `--remote NAME` | `origin` | Remote name to sync from |
| `--branches PATTERNS` | all | Comma-separated branch glob patterns (e.g., `main,release/*`) |
| `--json` | off | Output results as JSON (suppresses console output) |
| `--fetch-retries N` | 0 | Number of retries for failed fetches (exponential backoff) |
| `--config PATH` | auto | Path to `.pygitrc.toml` config file |
| `--version` | -- | Print version and exit |

## Architecture

```
CLI (main)
 |
 v
SyncOrchestrator          -- coordinates the full run
 |-- RepositoryScanner     -- finds repos via os.walk (symlink-safe)
 |-- BranchSynchronizer    -- syncs a single repo
 |    |-- BranchSyncStrategy (x5)  -- one strategy per branch state
 |    |-- GitRepository (protocol) -- abstracts git operations
 |    '-- OutputHandler (protocol) -- abstracts console/test output
 |-- SyncHook (abstract)   -- before/after/error plugin hooks
 '-- SummaryReporter       -- prints the final report
```

Output handler implementations:
- `ConsoleOutputHandler` -- colored terminal output
- `NullOutputHandler` -- silent (used in JSON mode and tests)
- `BufferedOutputHandler` -- collects messages for deferred flush (used in parallel mode)

Key design decisions:
- **Protocol-based DI**: `GitRepository` and `OutputHandler` are `typing.Protocol` classes, not abstract bases. Any object with the right methods works, no inheritance required. This makes testing trivial (`NullOutputHandler`, fake repos).
- **Strategy pattern**: Branch sync logic is split into 5 focused strategy classes. Adding a new scenario (e.g., "force-push detection") means adding one class and appending it to the strategy list.
- **Hooks**: `SyncHook` provides `before_sync`, `after_sync`, and `on_error` callbacks. A hook can skip repos, log results, send notifications, etc.
- **Immutable data**: `BranchInfo`, `SyncIssue`, `OperationResult`, and `SyncConfig` are frozen dataclasses. Only `SyncResult` and `BranchStatus` are mutable (they accumulate data during a run).

## Testing

```bash
source .venv/bin/activate
pytest tests/ -v
```

133 tests (76 unit + 57 integration):

- `test_domain_models.py` -- dataclass construction, `SyncResult` issue tracking and JSON serialization, `SyncConfig.with_updates()`, config file loading
- `test_strategies.py` -- each strategy's `can_handle()` and `sync()` with a fake `GitRepository`, change description output, branch filter matching
- `test_scanner.py` -- directory discovery, exclusion, symlink safety, deduplication, edge cases (`.git` files, nesting)
- `test_output_handlers.py` -- `NullOutputHandler` accepts all calls, `ConsoleOutputHandler` prints correctly, `BufferedOutputHandler` collects and flushes
- `test_integration.py` -- end-to-end tests using real bare repos as remotes and local clones. Covers fast-forward, dry-run, merge mode, stash-and-pull, stash conflict, new branch creation, stale branch deletion, `--no-remove-stale`, diverged/ahead detection, branch filter with globs, branch restoration, multi-repo sequential and parallel, exclude patterns, `--remote`, `--json`, config file, error handling (no remote, empty repo), verbose mode, and exit code behavior

## Project Structure

```
pygit-sync/
  pygit_sync/              -- main package
    __init__.py            -- public API re-exports
    models.py              -- enums, dataclasses (BranchInfo, SyncResult, SyncConfig, ...)
    protocols.py           -- GitRepository, OutputHandler, SyncHook interfaces
    repository.py          -- GitPythonRepository (concrete git implementation)
    output.py              -- ConsoleOutputHandler, NullOutputHandler, BufferedOutputHandler
    strategies.py          -- 5 branch sync strategy classes
    scanner.py             -- RepositoryScanner (finds git repos via os.walk)
    synchronizer.py        -- BranchSynchronizer (syncs a single repo)
    orchestrator.py        -- SyncOrchestrator (coordinates multi-repo sync)
    reporter.py            -- SummaryReporter (final report output)
    config.py              -- argument parser and TOML config loader
    cli.py                 -- main() entry point
  pyproject.toml           -- packaging metadata, dependencies & entry point
  LICENSE                  -- MIT license
  CHANGELOG.md             -- version history
  CONTRIBUTING.md          -- development & contribution guide
  .pygitrc.toml            -- (optional) persistent config
  .github/workflows/ci.yml -- GitHub Actions CI
  tests/
    __init__.py
    test_domain_models.py
    test_strategies.py
    test_scanner.py
    test_output_handlers.py
    test_integration.py
```

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing, and guidelines.

## License

MIT. See [LICENSE](LICENSE).
