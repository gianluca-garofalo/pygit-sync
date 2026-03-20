"""Configuration: argument parser and config file loader."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]


def create_argument_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with all pygit-sync flags."""
    # Lazy import to avoid circular dependency with __init__.py
    from pygit_sync import __version__

    parser = argparse.ArgumentParser(
        description="Recursively sync git repositories under a directory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s ~/projects                          # Dry-run preview
  %(prog)s ~/projects --execute                # Actually sync
  %(prog)s ~/projects --execute --parallel     # Parallel sync
  %(prog)s ~/projects --exclude node_modules   # Exclude patterns
        """
    )

    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    parser.add_argument('directory', nargs='?', default='.',
                       help='Directory to search (default: current)')

    behavior = parser.add_argument_group('behavior')
    behavior.add_argument('-x', '--execute', action='store_true',
                         help='Actually execute (default: dry-run)')
    behavior.add_argument('--no-rebase', dest='rebase', action='store_false',
                         help='Use merge instead of rebase')
    behavior.add_argument('--no-remove-stale', dest='remove_stale', action='store_false',
                         help='Keep stale branches')
    behavior.add_argument('--stash-and-pull', action='store_true',
                         help='Auto-stash local changes')
    behavior.add_argument('--create-branches', dest='create_branches', action='store_true',
                         help='Create local branches for remote-only branches')

    filtering = parser.add_argument_group('filtering')
    filtering.add_argument('--remote', default='origin', metavar='NAME',
                          help='Remote name to sync from (default: origin)')
    filtering.add_argument('--branches', type=str, default='', metavar='PATTERNS',
                          help='Comma-separated branch patterns to sync (e.g., "main,develop,release/*")')
    filtering.add_argument('--exclude', action='append', default=[], metavar='PATTERN',
                          help='Exclude pattern (can specify multiple)')
    filtering.add_argument('--max-branch-age', type=int, default=180, metavar='N',
                          help='Only create branches with commits newer than N days (default: 180, 0=no limit)')

    performance = parser.add_argument_group('performance')
    performance.add_argument('-p', '--parallel', action='store_true',
                            help='Sync repositories in parallel')
    performance.add_argument('--max-workers', type=int, default=min(os.cpu_count() or 4, 8), metavar='N',
                            help='Max parallel workers (default: min(cpu_count, 8))')
    performance.add_argument('--fetch-retries', type=int, default=0, metavar='N',
                            help='Number of retries for failed fetches (default: 0)')

    output = parser.add_argument_group('output')
    output.add_argument('-v', '--verbose', action='store_true',
                       help='Verbose output')
    output.add_argument('--json', dest='json_output', action='store_true',
                       help='Output results as JSON (suppresses normal output)')
    output.add_argument('--plain', action='store_true',
                       help='Disable emoji in output (for terminals with limited Unicode)')
    output.add_argument('--config', type=str, default=None, metavar='PATH',
                       help='Path to config file (default: .pygitrc.toml in search dir or home)')

    return parser


def load_config_file(search_dir: Path, config_path: str | None = None) -> dict[str, Any]:
    """Load .pygitrc.toml from explicit path, search dir, or home dir.

    Returns empty dict if not found or tomllib is unavailable.
    """
    candidates = [Path(config_path)] if config_path else [search_dir / '.pygitrc.toml', Path.home() / '.pygitrc.toml']
    for path in candidates:
        if path.is_file():
            if tomllib is None:
                print(f"Warning: Found {path} but tomllib/tomli not available (Python 3.11+ or pip install tomli). Ignoring.")
                return {}
            try:
                with open(path, 'rb') as f:
                    return tomllib.load(f)
            except Exception as e:
                print(f"Warning: Failed to parse {path}: {e}")
                return {}
    if config_path:
        print(f"Warning: Config file '{config_path}' not found. Ignoring.")
    return {}
