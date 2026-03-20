# Contributing to pygit-sync

Thanks for your interest in contributing! This document covers how to set up a development environment, run tests, and submit changes.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/pygit-sync.git
cd pygit-sync

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in editable mode with dev dependencies
pip install -e ".[dev]"
```

## Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=pygit_sync --cov-report=term-missing

# Run a specific test file
pytest tests/test_strategies.py -v
```

The test suite has 133 tests (76 unit + 57 integration). Integration tests create real git repositories in temporary directories — no network access or special setup is required.

## Code Style

This project uses [ruff](https://docs.astral.sh/ruff/) for linting:

```bash
# Check for lint errors
ruff check pygit_sync/

# Auto-fix what can be fixed
ruff check --fix pygit_sync/
```

Key conventions:
- Line length limit: 120 characters
- Target Python version: 3.9+
- All public classes and methods should have docstrings
- Use type hints for function signatures

## Project Structure

The package is split into 12 modules with a clean dependency graph:

```
models.py (leaf — no internal deps)
  -> protocols.py
    -> repository.py, output.py, strategies.py
      -> scanner.py, synchronizer.py
        -> orchestrator.py
          -> reporter.py, config.py, cli.py
```

When adding new functionality, keep this layering in mind — lower-level modules should not import from higher-level ones.

## Making Changes

1. Create a branch from `main`
2. Make your changes
3. Add or update tests as needed
4. Run `pytest tests/ -v` and `ruff check pygit_sync/` to verify
5. Commit with a clear message describing **why**, not just what
6. Open a pull request

## Adding a New Strategy

The sync logic uses the Strategy pattern. To add a new branch state handler:

1. Create a new class in `strategies.py` inheriting from `BranchSyncStrategy`
2. Implement `can_handle()` — return True when your scenario applies
3. Implement `sync()` — perform the action and return a `SyncIssue` or None
4. Add it to the `self.strategies` list in `BranchSynchronizer.__init__` (`synchronizer.py`)
5. Add tests in `test_strategies.py`

## Adding a New CLI Flag

1. Add the field to `SyncConfig` in `models.py`
2. Update `SyncConfig.with_updates()` if needed
3. Add `parser.add_argument(...)` in `config.py`
4. Wire it up in `cli.py` `main()` — handle both CLI args and config file values
5. Add integration tests in `test_integration.py`

## Reporting Issues

Open an issue on GitHub with:
- What you expected to happen
- What actually happened
- Steps to reproduce
- Python version and OS
