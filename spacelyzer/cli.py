"""
Command-line interface for Spacelyzer.

Run `spacelyzer --help` for a complete list of flags. The CLI is split
into:

  * ``main()``             — top-level argument parsing & dispatch
  * ``create_parser()``    — argparse definition
  * ``cmd_<subcommand>()`` — each named subcommand has its own function

Subcommands
-----------
  (default)        analyze a path
  snapshot         save a snapshot of the current scan
  history          list saved snapshots
  diff             compare two snapshots
  watch            live monitoring
  duplicates       find byte-identical files
  report           generate a self-contained HTML report

Even the default mode is one logical "analyze" command with a rich set
of flags; the subcommands are thin wrappers that pre-fill the right
flags for you.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from spacelyzer import __version__
from spacelyzer.exceptions import (
    PathNotFoundException,
    PermissionDeniedException,
    SpacelyzerException,
    UserCancelledException,
)
from spacelyzer.formatter import (
    format_bytes, get_color_codes, has_unicode_support, parse_size,
)
from spacelyzer.scanner import DiskScanner, ScanResults
from spacelyzer.similarity import SimilarityDetector
from spacelyzer.suggestions import SuggestionsAnalyzer
from spacelyzer.renderer import DiskUsageRenderer

from spacelyzer import snapshots as snap_mod
from spacelyzer import watch as watch_mod


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def _parse_age(s: str) -> float:
    """Parse '30d', '12h', '2w', '1y' → epoch seconds (the cutoff)."""
    if not s:
        return 0.0
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([smhdwMy])\s*$", s)
    if not m:
        raise argparse.ArgumentTypeError(
            f"Invalid age: '{s}' (use e.g. 30d, 12h, 2w, 1y)"
        )
    n = float(m.group(1))
    unit = m.group(2)
    now = time.time()
    factors = {
        "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 86400 * 7,
        "M": 86400 * 30, "y": 86400 * 365,
    }
    return now - n * factors[unit]


def _parse_interval(s: str) -> float:
    """Parse '5s', '2m' → seconds."""
    if not s:
        raise argparse.ArgumentTypeError("empty interval")
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([smh])\s*$", s)
    if not m:
        raise argparse.ArgumentTypeError(f"Invalid interval: '{s}' (use e.g. 5s, 2m)")
    n = float(m.group(1))
    unit = m.group(2)
    return n * {"s": 1, "m": 60, "h": 3600}[unit]


# --------------------------------------------------------------------------- #
#  Argument parser
# --------------------------------------------------------------------------- #
def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spacelyzer",
        description=(
            "Spacelyzer — read-only disk analyzer with smart-skip, dedup, "
            "snapshots, watch mode and rich terminal reports."
        ),
        epilog=(
            "Examples:\n"
            "  spacelyzer                     Analyze current directory.\n"
            "  spacelyzer ~/Projects          Analyze a specific path.\n"
            "  spacelyzer . --tree            Hierarchical tree view.\n"
            "  spacelyzer . --summary         Storage category bar graph.\n"
            "  spacelyzer . --duplicates      Find byte-identical files.\n"
            "  spacelyzer . --no-smart-skip   Fully recurse known folders.\n"
            "  spacelyzer watch ~/Downloads   Re-scan every 5s.\n"
            "  spacelyzer snapshot .          Save a snapshot for later diff.\n"
            "\n"
            "See 'spacelyzer <command> --help' for command-specific flags."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version",
                        version=f"Spacelyzer v{__version__}")

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # default
    p_analyze = sub.add_parser(
        "analyze", help="Analyze a path (default).",
        description=(
            "Analyze a directory tree. By default, well-known huge "
            "dependency / cache / build folders (node_modules, "
            "__pycache__, target, …) are smart-skipped: their total "
            "size is reported without enumerating their contents. "
            "Pass --no-smart-skip to fully recurse."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_common_flags(p_analyze)
    p_analyze.add_argument("path", nargs="?", default=".",
                           help="Directory to analyze (default: current dir).")
    p_analyze.set_defaults(func=cmd_analyze)

    p_snap = sub.add_parser(
        "snapshot", help="Save a scan snapshot.",
        description="Run a scan and persist a snapshot for later diffing.",
    )
    _add_common_flags(p_snap)
    p_snap.add_argument("path", nargs="?", default=".",
                        help="Directory to snapshot (default: current dir).")
    p_snap.add_argument("--label", help="Friendly name for the snapshot.")
    p_snap.set_defaults(func=cmd_snapshot)

    p_hist = sub.add_parser(
        "history", help="List saved snapshots for a path.",
        description="List snapshots previously saved with 'spacelyzer snapshot'.",
    )
    p_hist.add_argument("path", nargs="?", default=".")
    p_hist.add_argument("--json", action="store_true",
                        help="Emit history as JSON.")
    p_hist.set_defaults(func=cmd_history)

    p_diff = sub.add_parser(
        "diff", help="Compare two snapshots for a path.",
        description="Show what grew, shrank, was added, or was removed.",
    )
    p_diff.add_argument("path", nargs="?", default=".")
    p_diff.add_argument("--with", dest="with_snapshot", required=True,
                        help="Path to a previous snapshot file (from history).")
    p_diff.add_argument("--top", type=int, default=20,
                        help="Show the top N movers (default: 20).")
    p_diff.set_defaults(func=cmd_diff)

    p_watch = sub.add_parser(
        "watch", help="Re-scan and re-render at an interval.",
        description="Re-runs the analysis at a fixed interval. "
                    "Use Ctrl+C to stop.",
    )
    _add_common_flags(p_watch)
    p_watch.add_argument("path", nargs="?", default=".")
    p_watch.add_argument("--interval", type=_parse_interval, default=5.0,
                         help="Seconds between re-scans (e.g. 5s, 1m).")
    p_watch.add_argument("--iterations", type=int, default=None,
                         help="Stop after this many ticks (default: forever).")
    p_watch.set_defaults(func=cmd_watch)

    p_dup = sub.add_parser(
        "duplicates", help="Find byte-identical files (full content hash).",
        description="Group files with identical content using content hashing.",
    )
    _add_common_flags(p_dup)
    p_dup.add_argument("path", nargs="?", default=".")
    p_dup.add_argument("--hash", choices=["blake2b", "sha256"],
                       default="blake2b",
                       help="Hash algorithm (default: blake2b, ~3x faster).")
    p_dup.set_defaults(func=cmd_duplicates)

    p_report = sub.add_parser(
        "report", help="Write a self-contained HTML report.",
        description="Generate a single-file HTML report (no external assets).",
    )
    _add_common_flags(p_report)
    p_report.add_argument("path", nargs="?", default=".")
    p_report.set_defaults(func=cmd_report, output=None)

    return parser


def _add_common_flags(p: argparse.ArgumentParser) -> None:
    """Flags shared by analyze, snapshot, watch, duplicates, report."""
    p.add_argument("-d", "--depth", type=int, default=None,
                   help="Limit recursion depth.")
    p.add_argument("-n", "--top", type=int, default=None,
                   help="Show only the top N entries.")
    p.add_argument("-f", "--files", action="store_true",
                   help="Include files in results (default: folders only).")
    p.add_argument("--folders", action="store_true",
                   help="Show folders only, ignore files entirely.")
    p.add_argument("--hidden", action="store_true",
                   help="Include hidden files and folders (default: excluded).")
    p.add_argument("--follow-links", action="store_true",
                   help="Follow symbolic links (default: no).")
    p.add_argument("--sort", choices=["size", "name", "modified"],
                   default="size",
                   help="Sort by size (default), name, or modified time.")
    p.add_argument("-r", "--reverse", action="store_true",
                   help="Reverse sort order (ascending).")
    p.add_argument("--min", type=parse_size, default=0,
                   help="Ignore entries smaller than size (e.g. 100MB, 1GB).")
    p.add_argument("--max", type=parse_size, default=0,
                   help="Ignore entries larger than size (0 = unlimited).")
    p.add_argument("--bytes", action="store_true",
                   help="Show raw byte counts instead of human-readable sizes.")
    p.add_argument("--ignore", action="append", default=[],
                   help="Exclude paths matching pattern (repeatable).")
    p.add_argument("--gitignore", action="store_true",
                   help="Respect nearest .gitignore at every level.")
    p.add_argument("--query", type=str, default=None,
                   help="Regex matched against entry name.")
    p.add_argument("--ext", action="append", default=[],
                   help="Limit to specific extensions (repeatable).")
    p.add_argument("--newer-than", type=_parse_age, default=None,
                   help="Only entries modified in the last N (e.g. 30d, 12h).")
    p.add_argument("--older-than", type=_parse_age, default=None,
                   help="Only entries older than N (e.g. 90d, 1y).")
    p.add_argument("--workers", type=int, default=0,
                   help="Number of scanner workers (0 = auto).")
    p.add_argument("--no-progress", action="store_true",
                   help="Suppress the scanning progress indicator.")
    p.add_argument("--include-age", action="store_true",
                   help="Show the mtime-age column in the main table.")
    p.add_argument("--no-smart-skip", action="store_true",
                   help="Recurse into node_modules, __pycache__, target, etc.")

    # Modes
    p.add_argument("--tree", action="store_true",
                   help="Render a hierarchical tree view with sizes.")
    p.add_argument("--compact", action="store_true",
                   help="Compact table layout for narrow terminals.")
    p.add_argument("--largest-files", action="store_true",
                   help="List the largest individual files.")
    p.add_argument("--extensions", action="store_true",
                   help="Group and rank by file extension.")
    p.add_argument("--breakdown", action="store_true",
                   help="Show percentage breakdown of a folder's contents.")
    p.add_argument("--similar", action="store_true",
                   help="Detect similar and duplicate files / folders.")
    p.add_argument("--summary", action="store_true",
                   help="Show a storage-category bar graph.")
    p.add_argument("--fingerprint", action="store_true",
                   help="Show the Developer Storage Fingerprint.")
    p.add_argument("--age", action="store_true",
                   help="Show age distribution buckets.")
    p.add_argument("--categories", action="store_true",
                   help="Show storage-category summary bars.")

    # Visualizations
    p.add_argument("--bar", action="store_true",
                   help="Render a bar chart of the top N.")
    p.add_argument("--pie", action="store_true",
                   help="Render a Unicode pie chart.")
    p.add_argument("--sunburst", action="store_true",
                   help="Render an ASCII sunburst tree.")
    p.add_argument("--treemap", action="store_true",
                   help="Render a terminal treemap grid.")

    # Output formats
    p.add_argument("--format", choices=["table", "json", "csv", "markdown",
                                        "ndjson", "yaml", "html"],
                   default="table",
                   help="Output format (default: table).")
    p.add_argument("-o", "--output", default=None,
                   help="Write output to this file instead of stdout.")


# --------------------------------------------------------------------------- #
#  Common scan flow
# --------------------------------------------------------------------------- #
def _build_scanner(args) -> DiskScanner:
    scan_path = Path(args.path).resolve()
    return DiskScanner(
        root_path=str(scan_path),
        depth=args.depth,
        include_files=args.files,
        folders_only=args.folders,
        include_hidden=args.hidden,
        follow_links=args.follow_links,
        ignore_patterns=args.ignore,
        min_size=args.min,
        max_size=args.max,
        newer_than=args.newer_than,
        older_than=args.older_than,
        query=args.query,
        extensions=args.ext,
        gitignore=args.gitignore,
        workers=args.workers,
        show_progress=not args.no_progress,
        smart_skip=not args.no_smart_skip,
    )


def _format_output(text: str, output_path: Optional[str]) -> None:
    if output_path:
        Path(output_path).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()


def _run_scan(args) -> Tuple[Optional[ScanResults], int]:
    """Run a scan, handling all common failure modes.

    Returns ``(results, exit_code)``. On success, ``results`` is set and
    ``exit_code`` is ``0``. On any handled failure, ``results`` is ``None``
    and the CLI should return ``exit_code`` directly.
    """
    try:
        scanner = _build_scanner(args)
    except PathNotFoundException as e:
        print(f"Error: {e}", file=sys.stderr)
        return None, 3
    try:
        return scanner.scan(), 0
    except PermissionError as e:
        print(f"Permission denied: {e}", file=sys.stderr)
        return None, 2
    except PermissionDeniedException as e:
        print(f"Permission denied: {e}", file=sys.stderr)
        return None, 2
    except UserCancelledException as e:
        print(f"\n{e}", file=sys.stderr)
        return None, 4
    except KeyboardInterrupt:
        print("\nScan cancelled by user (Ctrl+C).", file=sys.stderr)
        return None, 4
    except Exception as e:
        print(f"Unknown error during scan: {e}", file=sys.stderr)
        return None, 1


# --------------------------------------------------------------------------- #
#  Subcommands
# --------------------------------------------------------------------------- #
def cmd_analyze(args) -> int:
    results, code = _run_scan(args)
    if results is None:
        return code

    # --format HTML is its own thing
    if args.format == "html":
        renderer = DiskUsageRenderer(results, args.bytes, args.depth)
        _format_output(renderer.render_html(title=f"Spacelyzer · {results.root_path}"),
                       args.output)
        return 0

    return _render_analyze_results(args, results)


def _render_analyze_results(args, results) -> int:
    """Render an analysis result based on CLI flags."""
    renderer = DiskUsageRenderer(results, args.bytes, args.depth)
    detector = SimilarityDetector(results.files,
                                  [e for e in results.entries.values() if e.is_dir])
    duplicates = detector.find_exact_duplicates()
    s_analyzer = SuggestionsAnalyzer(results.entries, duplicates)
    suggestions = s_analyzer.generate_suggestions()
    total_reclaimable = sum(s.total_size for s in suggestions)

    out: List[str] = []

    # ---- JSON / CSV / NDJSON / YAML / Markdown
    if args.format == "json":
        _format_output(renderer.render_json(), args.output)
        return 0
    if args.format == "csv":
        _format_output(renderer.render_csv(), args.output)
        return 0
    if args.format == "ndjson":
        _format_output(renderer.render_ndjson(), args.output)
        return 0
    if args.format == "yaml":
        _format_output(renderer.render_yaml(), args.output)
        return 0
    if args.format == "markdown":
        _format_output(renderer.render_markdown(), args.output)
        return 0

    # ---- Standalone analysis modes
    if args.tree:
        out.append(renderer.render_tree(args.depth, top_children=args.top))
    elif args.largest_files:
        out.append(renderer.render_largest_files(args.top or 10))
    elif args.extensions:
        out.append(renderer.render_extensions(args.top or 15))
    elif args.breakdown:
        out.append(renderer.render_breakdown(str(results.root_path)))
    elif args.similar:
        out.append(_render_similarity(args, detector, duplicates, args.bytes))
    elif args.summary:
        out.append(renderer.render_category_bars(args.bytes))
        out.append("")
        out.append(renderer.render_storage_fingerprint())
    elif args.fingerprint:
        out.append(renderer.render_storage_fingerprint())
    elif args.age:
        out.append(renderer.render_age_breakdown())
    elif args.categories:
        out.append(renderer.render_category_bars(args.bytes))
    elif args.bar:
        out.append(renderer.render_bar_chart(args.top or 8))
    elif args.pie:
        out.append(renderer.render_pie_chart())
    elif args.sunburst:
        out.append(renderer.render_sunburst())
    elif args.treemap:
        out.append(renderer.render_treemap())
    else:
        # ---- Default: header + table + smart-skip notice + categories
        #                 + suggestions + scan summary
        out.append(renderer.render_terminal_table(
            args.top, args.sort, args.reverse,
            include_age=args.include_age,
            compact=args.compact,
        ))
        if results.smart_skipped:
            out.append("")
            out.append(renderer.render_smart_skip_notice())
        out.append("")
        out.append(renderer.render_category_bars(args.bytes))
        out.append("")
        out.append(renderer.render_suggestions(suggestions, show_paths=True))
        out.append("")
        out.append(renderer.render_summary(total_reclaimable, duplicates))

    _format_output("\n".join(str(x) for x in out if x), args.output)
    return 0


def _render_similarity(args, detector: SimilarityDetector,
                       duplicates, raw_bytes: bool) -> str:
    colors = get_color_codes()
    c_bold, c_cyan, c_green, c_blue, c_yellow, c_red, c_reset = (
        colors["bold"], colors["cyan"], colors["green"],
        colors["blue"], colors["yellow"], colors["red"], colors["reset"]
    )
    has_uni = has_unicode_support()
    bullet = "·" if has_uni else "-"
    div = "─" * 60 if has_uni else "-" * 60
    dash = "—" if has_uni else "-"

    out = [f"{c_bold}{c_cyan}Similarity Detection{c_reset}", ""]
    similar_files = detector.find_similar_files()
    if similar_files:
        out.append(f"{c_bold}Similar files (by name + size){c_reset}")
        for name, group in similar_files[:10]:
            total = sum(f.size for f in group)
            out.append(
                f"  {c_yellow}{name}{c_reset}  {bullet}  {len(group)} files  {bullet}  "
                f"{c_green}{format_bytes(total, raw_bytes)}{c_reset}"
            )
            for f in group:
                out.append(
                    f"    {c_blue}{f.name}{c_reset}  "
                    f"{c_green}{format_bytes(f.size, raw_bytes):>10}{c_reset}  "
                    f"{f.path}"
                )
            out.append("")
    else:
        out.append("No similar files found.")
    out.append(div)
    similar_folders = detector.find_similar_folders()
    if similar_folders:
        out.append(f"{c_bold}Similar folders (by name){c_reset}")
        for name, group in similar_folders[:10]:
            total = sum(f.size for f in group)
            out.append(
                f"  {len(group)} copies of {c_yellow}{name}{c_reset}  {dash}  "
                f"{c_green}{format_bytes(total, raw_bytes)}{c_reset} combined"
            )
            for folder in group:
                out.append(
                    f"    {c_blue}{folder.path}{c_reset}  "
                    f"{c_green}{format_bytes(folder.size, raw_bytes)}{c_reset}"
                )
            out.append("")
    if duplicates:
        out.append(div)
        out.append(f"{c_bold}Exact duplicates (content-hashed){c_reset}")
        for name, group in duplicates[:10]:
            total = sum(f.size for f in group)
            reclaim = total - max(f.size for f in group)
            out.append(
                f"  {len(group)} copies of {c_yellow}{name}{c_reset}  "
                f"{dash}  {c_green}{format_bytes(total, raw_bytes)}{c_reset}  "
                f"({c_red}reclaimable: {format_bytes(reclaim, raw_bytes)}{c_reset})"
            )
            for f in group:
                out.append(
                    f"    {c_blue}{f.name}{c_reset}  "
                    f"{c_green}{format_bytes(f.size, raw_bytes):>10}{c_reset}  "
                    f"{f.path}"
                )
            out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
def cmd_snapshot(args) -> int:
    results, code = _run_scan(args)
    if results is None:
        return code
    path = snap_mod.save_snapshot(results, label=args.label)
    print(f"Saved snapshot: {path}")
    return 0


def cmd_history(args) -> int:
    files = snap_mod.list_snapshots(args.path if args.path != "." else None)
    if args.json:
        out = [{
            "path": str(p),
            "modified": p.stat().st_mtime,
            "size_bytes": p.stat().st_size,
        } for p in files]
        print(json.dumps(out, indent=2))
        return 0
    if not files:
        print("No snapshots saved yet. Use: spacelyzer snapshot [PATH]")
        return 0
    colors = get_color_codes()
    c_blue, c_green, c_dim, c_reset = (
        colors["blue"], colors["green"], colors["dim"], colors["reset"]
    )
    print(f"{c_blue}{'Snapshot':<60} {'Date':<20} {'Size':>10}{c_reset}")
    for p in files:
        st = p.stat()
        date = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))
        print(
            f"  {c_dim}{p.name:<60}{c_reset} {c_blue}{date:<20}{c_reset} "
            f"{c_green}{format_bytes(st.st_size):>10}{c_reset}"
        )
    return 0


def cmd_diff(args) -> int:
    files = snap_mod.list_snapshots(args.path if args.path != "." else None)
    if not files:
        print("No snapshots to compare.", file=sys.stderr)
        return 1
    new_path = Path(args.with_snapshot)
    if not new_path.exists():
        print(f"Snapshot not found: {new_path}", file=sys.stderr)
        return 1
    sorted_files = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
    new_full = snap_mod.load_snapshot(new_path)
    old_path = None
    for p in sorted_files:
        if p == new_path:
            continue
        if p.stat().st_mtime < new_path.stat().st_mtime:
            old_path = p
            break
    if old_path is None:
        print("No earlier snapshot found to compare against.", file=sys.stderr)
        return 1
    old_full = snap_mod.load_snapshot(old_path)
    diff = snap_mod.diff_snapshots(old_full, new_full)
    from spacelyzer.scanner import ScanResults
    fake = ScanResults(Path(new_full.path))
    fake.total_size = new_full.total_size
    renderer = DiskUsageRenderer(fake, args.bytes)
    print(renderer.render_diff(diff, top=args.top))
    print()
    print(f"old: {old_path}")
    print(f"new: {new_path}")
    return 0


def cmd_watch(args) -> int:
    def factory():
        return _build_scanner(args)

    def render_to_string(results) -> str:
        renderer = DiskUsageRenderer(results, args.bytes, args.depth)
        detector = SimilarityDetector(results.files,
                                      [e for e in results.entries.values() if e.is_dir])
        duplicates = detector.find_exact_duplicates()
        s_analyzer = SuggestionsAnalyzer(results.entries, duplicates)
        suggestions = s_analyzer.generate_suggestions()
        total = sum(s.total_size for s in suggestions)

        out = [renderer.render_terminal_table(
                   args.top, args.sort, args.reverse, include_age=args.include_age),
               "",
               renderer.render_category_bars(args.bytes),
               "",
               renderer.render_suggestions(suggestions, show_paths=True),
               "",
               renderer.render_summary(total, duplicates)]
        return "\n".join(x for x in out if x)

    try:
        watch_mod.watch(factory, render_to_string,
                        interval=args.interval, iterations=args.iterations,
                        show_progress=not args.no_progress)
    except (KeyboardInterrupt, UserCancelledException):
        # watch.py already prints the stop banner; swallow here
        pass
    return 0


def cmd_duplicates(args) -> int:
    results, code = _run_scan(args)
    if results is None:
        return code

    detector = SimilarityDetector(
        results.files,
        [e for e in results.entries.values() if e.is_dir],
        hash_algo=args.hash,
    )
    colors = get_color_codes()
    c_bold, c_cyan, c_green, c_blue, c_yellow, c_red, c_reset = (
        colors["bold"], colors["cyan"], colors["green"],
        colors["blue"], colors["yellow"], colors["red"], colors["reset"]
    )

    def _progress(done, total):
        sys.stderr.write(f"\rHashing: {done}/{total} suspect files   ")
        sys.stderr.flush()

    detector.progress_cb = _progress
    duplicates = detector.find_exact_duplicates()

    sys.stderr.write("\r" + " " * 60 + "\r")
    sys.stderr.flush()

    if not duplicates:
        print("No exact duplicate files found.")
        return 0

    out = [f"{c_bold}{c_cyan}Exact Duplicates (hash={args.hash}){c_reset}", ""]
    total_reclaimable = 0
    for name, group in duplicates[:args.top]:
        sizes = sorted([f.size for f in group], reverse=True)
        reclaim = sum(sizes[1:])
        total_reclaimable += reclaim
        out.append(
            f"  {c_bold}{len(group)} copies{c_reset} of {c_yellow}{name}{c_reset}  "
            f"{c_green}{format_bytes(sum(sizes), args.bytes)}{c_reset}  "
            f"({c_red}reclaimable: {format_bytes(reclaim, args.bytes)}{c_reset})"
        )
        for f in group:
            out.append(
                f"    {c_blue}{f.name}{c_reset}  "
                f"{c_green}{format_bytes(f.size, args.bytes):>10}{c_reset}  "
                f"{f.path}"
            )
        out.append("")
    out.append(f"{c_bold}Total reclaimable: "
               f"{c_green}{format_bytes(total_reclaimable, args.bytes)}{c_reset}")
    _format_output("\n".join(out), args.output)
    return 0


def cmd_report(args) -> int:
    results, code = _run_scan(args)
    if results is None:
        return code
    renderer = DiskUsageRenderer(results, args.bytes, args.depth)
    out_arg = getattr(args, "output", None)
    if not out_arg:
        safe_name = re.sub(r"[^\w\-.]", "_", results.root_path.name or "scan")
        out_arg = str(results.root_path.parent / f"{safe_name}-spacelyzer.html")
    out_path = Path(out_arg)
    out_path.write_text(renderer.render_html(title=f"Spacelyzer · {results.root_path}"),
                        encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


# --------------------------------------------------------------------------- #
#  Entry point
# --------------------------------------------------------------------------- #
def main(args_list: Optional[Sequence[str]] = None) -> int:
    """Entry point — parse args and dispatch to the appropriate subcommand.

    All exceptions are caught here so the user always sees a clean message
    instead of a raw Python traceback.
    """
    raw = list(args_list if args_list is not None else sys.argv[1:])
    parser = create_parser()
    if not raw or not _looks_like_subcommand(raw[0]):
        # Insert the default subcommand (backward-compatible with v1)
        raw = ["analyze"] + raw
    try:
        args = parser.parse_args(raw)
    except SystemExit as e:
        return int(e.code) if e.code is not None else 1

    try:
        return args.func(args)
    except KeyboardInterrupt:
        # User pressed Ctrl+C outside of an active scan (e.g. during render).
        print("\nInterrupted by user (Ctrl+C).", file=sys.stderr)
        return 4
    except UserCancelledException as e:
        print(f"\nCancelled: {e}", file=sys.stderr)
        return 4
    except PermissionDeniedException as e:
        print(f"Permission denied: {e}", file=sys.stderr)
        return 2
    except PathNotFoundException as e:
        print(f"Error: {e}", file=sys.stderr)
        return 3
    except SpacelyzerException as e:
        print(f"Error: {e}", file=sys.stderr)
        return e.exit_code
    except Exception as e:  # pylint: disable=broad-except
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1


def _looks_like_subcommand(token: str) -> bool:
    return token in {
        "analyze", "snapshot", "history", "diff", "watch",
        "duplicates", "report", "--help", "-h", "--version",
    }


if __name__ == "__main__":
    sys.exit(main())
