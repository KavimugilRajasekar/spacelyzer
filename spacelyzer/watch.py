"""
Live watch mode.

`spacelyzer --watch [N]` re-runs the scan at a fixed interval and shows how
the picture changes. It does NOT try to be a filesystem-event watcher
(that would require ``watchdog`` or platform-specific APIs); instead it just
re-scans periodically, which is plenty useful for typical drive-cleanup
sessions.

The output stream is ANSI-aware: lines are overwritten in place when stdout
is a TTY, otherwise new sections are printed.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Callable, Optional

from spacelyzer.scanner import DiskScanner, ScanResults
from spacelyzer.exceptions import UserCancelledException


def _terminal_size(default: int = 80) -> int:
    try:
        return os.get_terminal_size().columns
    except Exception:
        return default


def watch(
    scanner_factory: Callable[[], DiskScanner],
    render_func: Callable[[ScanResults], str],
    interval: float = 5.0,
    iterations: Optional[int] = None,
    show_progress: bool = True,
) -> None:
    """Re-scan and render at fixed interval.

    Parameters
    ----------
    scanner_factory
        Callable returning a fresh ``DiskScanner`` instance each tick.
    render_func
        Callable that turns ``ScanResults`` into a single string output.
    interval
        Seconds between scans.
    iterations
        ``None`` → run forever; otherwise stop after this many ticks.
    """
    if interval < 0.5:
        interval = 0.5

    is_tty = sys.stdout.isatty()
    tick = 0
    last_results: Optional[ScanResults] = None

    try:
        # Render an empty placeholder immediately so the user sees *something*
        # before the first real scan completes.  This is inside the try/except
        # so that a Ctrl+C at this early stage is still caught cleanly.
        print(f"{render_func(_placeholder_results(scanner_factory()))}", end="")

        while True:
            tick += 1
            scanner = scanner_factory()
            scanner.show_progress = False
            results = scanner.scan()
            output = render_func(results)

            if is_tty:
                # Clear & rewrite
                width = _terminal_size()
                lines = output.splitlines() or [""]
                clear = "\x1b[2J\x1b[H"
                sys.stdout.write(clear)
                sys.stdout.write(output)
                if not output.endswith("\n"):
                    sys.stdout.write("\n")
                sys.stdout.flush()
            else:
                banner = f"\n--- tick {tick} at {time.strftime('%H:%M:%S')} ---\n"
                sys.stdout.write(banner)
                sys.stdout.write(output)
                if not output.endswith("\n"):
                    sys.stdout.write("\n")
                sys.stdout.flush()

            last_results = results
            if iterations is not None and tick >= iterations:
                return
            time.sleep(interval)
    except (KeyboardInterrupt, UserCancelledException):
        sys.stdout.write("\n[watch stopped by user]\n")


def _placeholder_results(scanner: DiskScanner) -> ScanResults:
    """Build an empty results container used only for the first render."""
    from spacelyzer.scanner import ScanResults
    return ScanResults(scanner.root_path)