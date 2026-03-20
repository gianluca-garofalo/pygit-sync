# PyGit-Sync Project Context

## Project Overview
- Python CLI tool (`pygit-sync`), package name `pygit_sync/` (12 modules)
- Uses GitPython, colorama, tqdm
- Architecture: Strategy pattern, Protocol-based DI, hooks system
- Version: 1.2.0
- Entry point: `pygit_sync.cli:main`

## Package Structure
- `models.py` — enums + dataclasses (IssueType, OperationType, BranchInfo, BranchStatus, SyncIssue, OperationResult, SyncResult, SyncConfig)
- `protocols.py` — GitRepository, OutputHandler, SyncHook
- `repository.py` — GitPythonRepository
- `output.py` — Console/Null/Buffered handlers + SECTION_WIDTH
- `strategies.py` — 5 branch sync strategies with `_e()` helper for plain mode
- `scanner.py` — RepositoryScanner (no internal deps)
- `synchronizer.py` — BranchSynchronizer with `_e()` helper for plain mode
- `orchestrator.py` — SyncOrchestrator with `_show_progress()` helper
- `reporter.py` — SummaryReporter with `_e()` helper for plain mode
- `config.py` — argparser (grouped: behavior, filtering, performance, output) + TOML config loader (lazy `__version__` import to avoid circular dep)
- `cli.py` — main(), colorama_init(), sentinel-based CLI detection
- `__init__.py` — re-exports all public API, `__version__`

## Key Design Decisions
- `config.py` uses lazy import `from pygit_sync import __version__` inside function body to avoid circular import with `__init__.py`
- `colorama_init()` is called in `cli.py:main()`, not at import time, so library usage doesn't modify global terminal state
- CLI-explicit detection uses a sentinel-default re-parse to reliably detect which flags the user set (supports `--flag=value` syntax and argparse prefix matching)
- Stale branch detection only deletes branches that *had* a tracking upstream (checked via `tracking_branch is not None or has_tracking_config`). Safe delete (`-d`) is tried first; force delete (`-D`) only if the branch has unmerged commits
- `os.walk(followlinks=False)` for symlink-safe directory traversal in scanner
- `BufferedOutputHandler` per thread in parallel mode, flushed under lock
- Pre-stash sync: with `--stash-and-pull`, dirty changes are stashed once before the branch loop (enabling checkout to other branches), then restored after
- Smart checkout: only checks out branches that are behind remote (avoids unnecessary checkout failures)
- `create_branches` defaults to `False` — use `--create-branches` to opt in
- `--max-branch-age` (default 180 days) filters branch creation; only effective with `--create-branches`
- Plain mode (`--plain`): all emoji replaced with ASCII fallbacks via `_e()` helper on strategies, synchronizer, and reporter

## Testing
- 133 tests: 76 unit + 57 integration
- Run with: `pytest tests/ -v`
- Integration tests use bare repos as remotes + local clones
- Default branch must be set explicitly with `-b main` (system default may be `master`)
- Repos without remotes: `repos_processed=0` (error in `_sync_single_repo` creates fresh SyncResult)
