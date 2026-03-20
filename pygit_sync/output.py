"""Output handler implementations: console, null, buffered."""

from __future__ import annotations

from colorama import Fore, Style
from tqdm import tqdm

from pygit_sync.protocols import OutputHandler

SECTION_WIDTH = 50


class ConsoleOutputHandler:
    """Console output with colors."""

    def __init__(self, verbose: bool = False):
        """Create a console handler. Set verbose=True to enable debug output."""
        self.verbose = verbose

    def info(self, message: str, indent: int = 0) -> None:
        """Print an informational message."""
        tqdm.write("  " * indent + message)

    def success(self, message: str, indent: int = 0) -> None:
        """Print a green success message."""
        tqdm.write("  " * indent + f"{Fore.GREEN}{message}{Style.RESET_ALL}")

    def warning(self, message: str, indent: int = 0) -> None:
        """Print a yellow warning message."""
        tqdm.write("  " * indent + f"{Fore.YELLOW}{message}{Style.RESET_ALL}")

    def error(self, message: str, indent: int = 0) -> None:
        """Print a red error message."""
        tqdm.write("  " * indent + f"{Fore.RED}{message}{Style.RESET_ALL}")

    def section(self, title: str) -> None:
        """Print a section header with a divider line."""
        tqdm.write("")
        tqdm.write(title)
        tqdm.write("-" * SECTION_WIDTH)

    def debug(self, message: str) -> None:
        """Print a cyan debug message (only when verbose is enabled)."""
        if self.verbose:
            tqdm.write(f"{Fore.CYAN}[DEBUG] {message}{Style.RESET_ALL}")


class NullOutputHandler:
    """Silent output handler for testing and JSON mode."""

    def info(self, message: str, indent: int = 0) -> None:
        """No-op."""
        pass

    def success(self, message: str, indent: int = 0) -> None:
        """No-op."""
        pass

    def warning(self, message: str, indent: int = 0) -> None:
        """No-op."""
        pass

    def error(self, message: str, indent: int = 0) -> None:
        """No-op."""
        pass

    def section(self, title: str) -> None:
        """No-op."""
        pass

    def debug(self, message: str) -> None:
        """No-op."""
        pass


class BufferedOutputHandler:
    """Collects output messages for deferred printing (used in parallel mode)."""

    def __init__(self):
        """Initialize with an empty message buffer."""
        self.messages: list[str] = []

    def info(self, message: str, indent: int = 0) -> None:
        """Buffer an informational message."""
        self.messages.append("  " * indent + message)

    def success(self, message: str, indent: int = 0) -> None:
        """Buffer a green success message."""
        self.messages.append("  " * indent + f"{Fore.GREEN}{message}{Style.RESET_ALL}")

    def warning(self, message: str, indent: int = 0) -> None:
        """Buffer a yellow warning message."""
        self.messages.append("  " * indent + f"{Fore.YELLOW}{message}{Style.RESET_ALL}")

    def error(self, message: str, indent: int = 0) -> None:
        """Buffer a red error message."""
        self.messages.append("  " * indent + f"{Fore.RED}{message}{Style.RESET_ALL}")

    def section(self, title: str) -> None:
        """Buffer a section header with a divider line."""
        self.messages.append("")
        self.messages.append(title)
        self.messages.append("-" * SECTION_WIDTH)

    def debug(self, message: str) -> None:
        """No-op (debug suppressed in parallel mode)."""
        pass

    def flush_to(self, target: OutputHandler) -> None:
        """Write all buffered messages to a target handler and clear the buffer."""
        for msg in self.messages:
            target.info(msg)
        self.messages.clear()
