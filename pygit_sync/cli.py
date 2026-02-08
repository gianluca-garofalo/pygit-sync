"""CLI entry point: main() function."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from colorama import Fore, Style

from pygit_sync.config import create_argument_parser, load_config_file
from pygit_sync.models import SyncConfig
from pygit_sync.orchestrator import SyncOrchestrator
from pygit_sync.output import ConsoleOutputHandler, NullOutputHandler
from pygit_sync.reporter import SummaryReporter


def main():
    """Main entry point"""
    parser = create_argument_parser()
    args = parser.parse_args()

    search_dir = Path(args.directory).resolve()
    if not search_dir.exists() or not search_dir.is_dir():
        print(f"{Fore.RED}Error: Invalid directory '{search_dir}'{Style.RESET_ALL}")
        sys.exit(1)

    file_config = load_config_file(search_dir, args.config)

    # Determine which args were explicitly set on CLI
    cli_explicit = set()
    for action in parser._actions:
        if action.dest in ('help', 'version'):
            continue
        for opt_string in action.option_strings:
            if opt_string in sys.argv:
                cli_explicit.add(action.dest)
                break

    def effective(dest: str, toml_key: str, transform=None):
        if dest in cli_explicit:
            val = getattr(args, dest)
            return transform(val) if transform else val
        if toml_key in file_config:
            return file_config[toml_key]
        val = getattr(args, dest)
        return transform(val) if transform else val

    branch_patterns_raw = effective('branches', 'branch_patterns')
    if isinstance(branch_patterns_raw, str):
        branch_patterns = [p.strip() for p in branch_patterns_raw.split(',') if p.strip()]
    else:
        branch_patterns = list(branch_patterns_raw) if branch_patterns_raw else []

    exclude_raw = effective('exclude', 'exclude_patterns')
    exclude_patterns = list(exclude_raw) if exclude_raw else []

    config = SyncConfig(
        dry_run=not effective('execute', 'execute'),
        use_rebase=effective('rebase', 'use_rebase'),
        remove_stale=effective('remove_stale', 'remove_stale'),
        stash_and_pull=effective('stash_and_pull', 'stash_and_pull'),
        parallel=effective('parallel', 'parallel'),
        max_workers=effective('max_workers', 'max_workers'),
        exclude_patterns=exclude_patterns,
        verbose=effective('verbose', 'verbose'),
        remote_name=effective('remote', 'remote_name'),
        branch_patterns=branch_patterns,
        json_output=effective('json_output', 'json_output'),
        fetch_retries=effective('fetch_retries', 'fetch_retries'),
    )

    logging.basicConfig(
        level=logging.DEBUG if config.verbose else logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    output = NullOutputHandler() if config.json_output else ConsoleOutputHandler(verbose=config.verbose)

    orchestrator = SyncOrchestrator(config, output)

    try:
        result = orchestrator.sync_all(search_dir)

        if config.json_output:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            reporter = SummaryReporter(output)
            reporter.print_summary(result, config)

        sys.exit(1 if result.has_critical_issues() else 0)

    except KeyboardInterrupt:
        if not config.json_output:
            output.warning("\n\nInterrupted by user")
        sys.exit(130)
    except Exception as e:
        if config.json_output:
            print(json.dumps({'error': str(e)}, indent=2))
        else:
            output.error(f"\nUnexpected error: {e}")
            if config.verbose:
                import traceback
                traceback.print_exc()
        sys.exit(1)
