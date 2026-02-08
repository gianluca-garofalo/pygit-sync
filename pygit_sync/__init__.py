"""
pygit-sync: Git Repository Sync Tool

Recursively discovers git repositories under a directory and synchronizes
each one with its remote.
"""

from colorama import init as colorama_init

colorama_init(autoreset=True)

__version__ = "1.1.0"

# Re-export public API so `from pygit_sync import X` keeps working.
from pygit_sync.cli import main  # noqa: E402
from pygit_sync.config import create_argument_parser, load_config_file  # noqa: E402
from pygit_sync.models import (  # noqa: E402
    BranchInfo,
    BranchStatus,
    IssueType,
    OperationResult,
    OperationType,
    SyncConfig,
    SyncIssue,
    SyncResult,
)
from pygit_sync.orchestrator import SyncOrchestrator  # noqa: E402
from pygit_sync.output import (  # noqa: E402
    SECTION_WIDTH,
    BufferedOutputHandler,
    ConsoleOutputHandler,
    NullOutputHandler,
)
from pygit_sync.protocols import GitRepository, OutputHandler, SyncHook  # noqa: E402
from pygit_sync.reporter import SummaryReporter  # noqa: E402
from pygit_sync.repository import GitPythonRepository  # noqa: E402
from pygit_sync.scanner import RepositoryScanner  # noqa: E402
from pygit_sync.strategies import (  # noqa: E402
    AheadOfRemoteStrategy,
    BranchSyncStrategy,
    CleanFastForwardStrategy,
    DirtyWorkingTreeStrategy,
    DivergedBranchStrategy,
    UpToDateStrategy,
)
from pygit_sync.synchronizer import BranchSynchronizer  # noqa: E402

__all__ = [
    "__version__",
    # Models
    "BranchInfo",
    "BranchStatus",
    "IssueType",
    "OperationResult",
    "OperationType",
    "SyncConfig",
    "SyncIssue",
    "SyncResult",
    # Protocols
    "GitRepository",
    "OutputHandler",
    "SyncHook",
    # Implementations
    "GitPythonRepository",
    "BufferedOutputHandler",
    "ConsoleOutputHandler",
    "NullOutputHandler",
    "SECTION_WIDTH",
    # Strategies
    "AheadOfRemoteStrategy",
    "BranchSyncStrategy",
    "CleanFastForwardStrategy",
    "DivergedBranchStrategy",
    "DirtyWorkingTreeStrategy",
    "UpToDateStrategy",
    # Services
    "BranchSynchronizer",
    "RepositoryScanner",
    "SyncOrchestrator",
    "SummaryReporter",
    # Config / CLI
    "create_argument_parser",
    "load_config_file",
    "main",
]
