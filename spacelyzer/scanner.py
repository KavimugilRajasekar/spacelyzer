"""
Parallel-aware disk scanner with rich filtering.

Highlights
----------
- **Bottom-up folder sizes**: a single post-order pass accumulates sizes
  into parents, no second disk walk required.
- **Coarse-grained parallelism**: directory enumeration is the slow part on
  most filesystems, so we use a `ThreadPoolExecutor` to fan out `os.scandir`
  across workers. The aggregation step (which is CPU-only) is single-threaded.
- **Filtering**: `--ignore`, `--gitignore`, `--hidden`, mtime filters,
  extension / name queries, `--min-size`, `--follow-links`.
- **Smart-skip**: well-known huge folders (``node_modules``, ``__pycache__``,
  ``target``, ``dist``, ``.gradle``, …) are size-only by default: we
  ``os.scandir`` once, sum the immediate files, and recurse one level
  for the obvious nested store directories (``.pnpm``) — never fully
  recursing. Disable with ``--no-smart-skip``.
- **Progress reporting**: tries `tqdm`, falls back to a stderr spinner.
- **Safety**: never descends into known Windows pseudo-folders
  (`System Volume Information`, `$Recycle.Bin`, …) and handles
  `PermissionError` gracefully on subfolders.
"""

from __future__ import annotations

import fnmatch
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from spacelyzer.analyzer import SMART_SKIP_FOLDERS
from spacelyzer.exceptions import PathNotFoundException
from spacelyzer.formatter import has_unicode_support


# --------------------------------------------------------------------------- #
#  Result containers
# --------------------------------------------------------------------------- #
class EntryInfo:
    """Metadata for a single filesystem entry."""

    __slots__ = (
        "path", "is_dir", "size", "name", "modified", "_age_bucket",
        "_smart_summary",
    )

    def __init__(self, path: Path, is_dir: bool, size: int = 0):
        self.path: Path = path
        self.is_dir: bool = is_dir
        self.size: int = size
        self.name: str = path.name or str(path)
        self.modified: float = 0.0
        try:
            st = path.lstat() if path.is_symlink() else path.stat()
            self.modified = float(st.st_mtime)
        except Exception:
            self.modified = 0.0
        self._age_bucket: Optional[str] = None
        # When True, this entry represents a folder whose contents were
        # *not* fully recursed into — the size is an aggregate.
        self._smart_summary: bool = False


class ScanResults:
    """Aggregated scan output consumed by renderers."""

    def __init__(self, root_path: Path):
        self.root_path: Path = root_path
        self.total_size: int = 0
        self.folders_scanned: int = 0
        self.files_scanned: int = 0
        self.elapsed_time: float = 0.0
        self.max_depth_reached: int = 0
        # Map absolute path string → EntryInfo
        self.entries: Dict[str, EntryInfo] = {}
        # parent path → list of child paths
        self.hierarchy: Dict[str, List[str]] = {}
        # Files (kept separate for top-N / dedup / extension analyses)
        self.files: List[EntryInfo] = []
        # Set of unique extensions
        self.extensions: Set[str] = set()
        # Per-category size sums (set during finalize())
        self.category_sizes: Dict[str, int] = {}
        # Per-extension (size, count) tuples
        self.extension_stats: Dict[str, Tuple[int, int]] = {}
        # Per-age-bucket (size, count)
        self.age_buckets: Dict[str, Tuple[int, int]] = {}
        # Largest individual files (sorted, capped during finalize())
        self.largest_files: List[EntryInfo] = []
        # Average file size (bytes)
        self.avg_file_size: float = 0.0
        # Median file size (bytes)
        self.median_file_size: float = 0.0
        # Folders that were *not* recursed into (size-only summary)
        self.smart_skipped: List[EntryInfo] = []


# --------------------------------------------------------------------------- #
#  Progress reporter
# --------------------------------------------------------------------------- #
class _Progress:
    """Wrap tqdm if available; otherwise print a CR spinner to stderr."""

    def __init__(self, enabled: bool):
        self.enabled = enabled
        self._bar = None
        self._spin_idx = 0
        self._spin_chars = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
        self._spin_fallback = ['|', '/', '-', '\\']
        self._last_update = 0.0
        self._tqdm_cls = None
        if enabled:
            try:
                from tqdm import tqdm  # type: ignore

                self._tqdm_cls = tqdm
            except Exception:
                self._tqdm_cls = None
            if self._tqdm_cls is None:
                # Test unicode support once
                self._use_unicode = has_unicode_support()
                # Make sure we have a tty before spamming stderr
                self._use_stderr = sys.stderr.isatty()

    def __enter__(self) -> "_Progress":
        if self.enabled and self._tqdm_cls is not None:
            self._bar = self._tqdm_cls(
                total=None,
                desc="Scanning",
                unit=" entries",
                file=sys.stderr,
                dynamic_ncols=True,
                mininterval=0.1,
                maxinterval=0.5,
            )
        return self

    def __exit__(self, *exc) -> None:
        if self._bar is not None:
            self._bar.close()
        elif self.enabled:
            sys.stderr.write("\r" + " " * 80 + "\r")
            sys.stderr.flush()

    def update(self, folders: int, files: int) -> None:
        if not self.enabled:
            return
        if self._bar is not None:
            self._bar.n = folders + files
            self._bar.set_postfix(folders=folders, files=files, refresh=False)
            self._bar.update(0)
            return
        # Fallback spinner
        now = time.time()
        if now - self._last_update < 0.1:
            return
        self._last_update = now
        if not getattr(self, "_use_stderr", False):
            return
        chars = self._spin_chars if self._use_unicode else self._spin_fallback
        c = chars[self._spin_idx % len(chars)]
        self._spin_idx += 1
        try:
            sys.stderr.write(
                f"\rScanning... {c}  {folders:,} folders, {files:,} files scanned"
            )
            sys.stderr.flush()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
#  Scanner
# --------------------------------------------------------------------------- #
class DiskScanner:
    def __init__(
        self,
        root_path: str,
        depth: Optional[int] = None,
        include_files: bool = False,
        folders_only: bool = False,
        include_hidden: bool = False,
        follow_links: bool = False,
        ignore_patterns: Optional[Sequence[str]] = None,
        min_size: int = 0,
        max_size: int = 0,                       # 0 = unlimited
        newer_than: Optional[float] = None,      # mtime epoch seconds
        older_than: Optional[float] = None,
        query: Optional[str] = None,
        extensions: Optional[Sequence[str]] = None,
        gitignore: bool = False,
        workers: int = 0,                        # 0 = auto
        show_progress: bool = True,
        smart_skip: bool = True,
    ):
        self.root_path = Path(root_path).resolve()
        self.depth = depth
        self.include_files = include_files
        self.folders_only = folders_only
        self.include_hidden = include_hidden
        self.follow_links = follow_links
        self.ignore_patterns: List[str] = list(ignore_patterns or [])
        self.min_size = max(0, int(min_size or 0))
        self.max_size = max(0, int(max_size or 0))
        self.newer_than = newer_than
        self.older_than = older_than
        self.query_re: Optional[re.Pattern] = (
            re.compile(query, re.IGNORECASE) if query else None
        )
        self.extensions_filter: Optional[Set[str]] = (
            {e.lower() if e.startswith(".") else "." + e.lower() for e in extensions}
            if extensions else None
        )
        self.gitignore = gitignore
        # Resolve gitignore patterns lazily, only if enabled
        self._gitignore_cache: Dict[Path, List[re.Pattern]] = {}
        self.workers = max(1, workers or min(32, (os.cpu_count() or 4) * 4))
        self.show_progress = show_progress
        self.smart_skip = smart_skip

        # Pseudo-folders on Windows that always raise access errors and add
        # no informational value.
        self._win_skip_names: Set[str] = (
            {
                "System Volume Information",
                "$Recycle.Bin",
                "$RECYCLE.BIN",
                "$WinREAgent",
                "$WINDOWS.~BT",
                "$WINDOWS.~WS",
                "Recovery",
                "DumpStack.log.tmp",
            }
            if os.name == "nt"
            else set()
        )

        if not self.root_path.exists():
            raise PathNotFoundException(f"Path not found: {root_path}")

    # ------------------------------------------------------------------ #
    #  Filtering helpers
    # ------------------------------------------------------------------ #
    def _is_hidden(self, path: Path) -> bool:
        if path.name.startswith("."):
            return True
        if os.name == "nt":
            try:
                import stat
                attrs = path.stat().st_file_attributes
                return bool(attrs & stat.FILE_ATTRIBUTE_HIDDEN)
            except Exception:
                pass
        return False

    def _load_gitignore(self, folder: Path) -> List[re.Pattern]:
        """Read & compile the .gitignore at *folder* (cached)."""
        if folder in self._gitignore_cache:
            return self._gitignore_cache[folder]
        patterns: List[re.Pattern] = []
        gi = folder / ".gitignore"
        if gi.is_file():
            try:
                lines = gi.read_text(encoding="utf-8", errors="ignore").splitlines()
            except Exception:
                lines = []
            for raw in lines:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                neg = line.startswith("!")
                if neg:
                    line = line[1:].strip()
                # Translate glob → regex on basename only
                regex = _glob_to_regex(line)
                try:
                    patterns.append(re.compile(regex, re.IGNORECASE))
                except re.error:
                    pass
        self._gitignore_cache[folder] = patterns
        return patterns

    def _is_gitignored(self, parent: Path, name: str) -> bool:
        if not self.gitignore:
            return False
        patterns = self._load_gitignore(parent)
        if not patterns:
            return False
        for pat in patterns:
            if pat.search(name):
                return True
        return False

    def _should_ignore(self, path: Path) -> bool:
        if not self.include_hidden and self._is_hidden(path):
            return True
        # Match against the basename and the full path string
        name = path.name
        path_str = str(path)
        for pat in self.ignore_patterns:
            if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(path_str, pat):
                return True
        if self._is_gitignored(path.parent, name):
            return True
        return False

    def _passes_mtime(self, mtime: float) -> bool:
        if self.newer_than is not None and mtime < self.newer_than:
            return False
        if self.older_than is not None and mtime > self.older_than:
            return False
        return True

    def _passes_query(self, path: Path) -> bool:
        if self.query_re is None and self.extensions_filter is None:
            return True
        if self.query_re is not None and self.query_re.search(path.name):
            return True
        if self.extensions_filter is not None and path.suffix.lower() in self.extensions_filter:
            return True
        # If either filter was set but didn't match, exclude
        return False

    # ------------------------------------------------------------------ #
    #  Smart-skip helpers
    # ------------------------------------------------------------------ #
    def _should_smart_skip(self, name: str) -> bool:
        """Return True if *name* is a folder we should summarize, not recurse."""
        if not self.smart_skip:
            return False
        return name in SMART_SKIP_FOLDERS

    def _summarize_folder(self, path: Path) -> int:
        """Compute the total size of *path* WITHOUT recursing fully.

        Strategy:
        1. ``os.scandir`` the folder once.
        2. For every immediate file, add its size and remember the file.
        3. For immediate subdirectories, do a single ``os.scandir`` to
           get their total size (one level of recursion only). This
           gives a fast, accurate enough aggregate for the things the
           user actually wants — e.g. each package inside ``.pnpm``,
           each module inside ``node_modules`` is reported as one
           block; we don't enumerate every file inside.

        Returns the total size in bytes.
        """
        total = 0
        try:
            entries = list(os.scandir(path))
        except (PermissionError, FileNotFoundError, OSError):
            return 0

        for entry in entries:
            try:
                if entry.is_file(follow_symlinks=self.follow_links):
                    try:
                        st = entry.stat(follow_symlinks=self.follow_links)
                        total += int(st.st_size)
                    except Exception:
                        pass
                elif entry.is_dir(follow_symlinks=self.follow_links):
                    # One level deeper only
                    total += self._summarize_one_level(Path(entry.path))
            except Exception:
                continue
        return total

    def _summarize_one_level(self, path: Path) -> int:
        """Sum the *immediate* file sizes in *path* — no recursion."""
        total = 0
        try:
            entries = list(os.scandir(path))
        except (PermissionError, FileNotFoundError, OSError):
            return 0
        for entry in entries:
            try:
                if entry.is_file(follow_symlinks=self.follow_links):
                    try:
                        st = entry.stat(follow_symlinks=self.follow_links)
                        total += int(st.st_size)
                    except Exception:
                        pass
                elif entry.is_dir(follow_symlinks=self.follow_links):
                    # Second level: one more scandir, count each child
                    # as a constant contribution. This keeps pnpm/.pnpm
                    # accurate-ish without exploding the work.
                    try:
                        sub_entries = list(os.scandir(entry.path))
                    except Exception:
                        continue
                    for sub in sub_entries:
                        try:
                            if sub.is_file(follow_symlinks=self.follow_links):
                                st = sub.stat(follow_symlinks=self.follow_links)
                                total += int(st.st_size)
                            elif sub.is_dir(follow_symlinks=self.follow_links):
                                # Add a flat 4 KB estimate per deeper dir
                                # (a representative file count) — this
                                # is good enough for a summary number.
                                total += 4096
                        except Exception:
                            continue
            except Exception:
                continue
        return total

    def _add_smart_summary(
        self, results: ScanResults, path: Path, size: int, mtime: float
    ) -> None:
        """Register *path* as a size-only entry in *results*."""
        info = EntryInfo(path, is_dir=True, size=size)
        info.modified = mtime
        info._smart_summary = True
        results.entries[str(path)] = info
        results.smart_skipped.append(info)
        results.folders_scanned += 1

    # ------------------------------------------------------------------ #
    #  Main scan
    # ------------------------------------------------------------------ #
    def scan(self) -> ScanResults:
        start = time.time()
        results = ScanResults(self.root_path)
        # Cancellation flag flipped by KeyboardInterrupt in the main thread;
        # background workers check it between scandir calls and bail out.
        self._cancelled = False

        # Phase 1 — discover all entries (parallel enumeration)
        all_folders: List[Tuple[Path, int]] = []
        folder_files_sizes: Dict[str, int] = {}

        # Build the work-queue with bounded depth
        work: List[Tuple[Path, int]] = [(self.root_path, 0)]
        # Pre-stash the root
        results.hierarchy[str(self.root_path)] = []

        progress = _Progress(self.show_progress)
        root_blocked_error: List[BaseException] = []

        def _walk(path: Path, depth: int) -> Tuple[
            int, int, List[Tuple[Path, int]], Dict[str, int], Dict[str, List[str]]
        ]:
            """Enumerate *path* once.

            Returns (folder_count, file_count, subfolders, local_files_sizes,
                     local_hierarchy) for the immediate directory only.
            """
            local_files_sizes: Dict[str, int] = {}
            local_hierarchy: Dict[str, List[str]] = {str(path): []}
            folder_count = 1
            file_count = 0
            subfolders: List[Tuple[Path, int]] = []
            curr_str = str(path)
            try:
                entries = list(os.scandir(path))
            except PermissionError as e:
                # Permission denied on the root is fatal — surface it
                if path == self.root_path:
                    root_blocked_error.append(e)
                return folder_count, file_count, subfolders, local_files_sizes, local_hierarchy
            except (FileNotFoundError, OSError):
                return folder_count, file_count, subfolders, local_files_sizes, local_hierarchy

            local_files_size = 0
            for entry in entries:
                if self._cancelled:
                    return folder_count, file_count, subfolders, local_files_sizes, local_hierarchy
                try:
                    entry_path = Path(entry.path)

                    if entry.name in self._win_skip_names:
                        continue

                    if self._should_ignore(entry_path):
                        continue

                    is_symlink = entry.is_symlink()
                    if is_symlink and not self.follow_links:
                        continue

                    if entry.is_dir(follow_symlinks=self.follow_links):
                        # Smart-skip: summarize known huge folders instead
                        # of recursing into them. We still add them to the
                        # hierarchy so phase-2 size aggregation can include
                        # their sizes when summing into the parent — and so
                        # tree renderers can show them as a single leaf node.
                        if self._should_smart_skip(entry.name):
                            try:
                                st = entry.stat(follow_symlinks=self.follow_links)
                                mtime = float(st.st_mtime)
                                size = self._summarize_folder(entry_path)
                            except Exception:
                                continue
                            self._add_smart_summary(
                                results, entry_path, size, mtime
                            )
                            # Visible as a child of the current folder so
                            # the parent gets its size rolled up.
                            local_hierarchy[curr_str].append(str(entry_path))
                            # Don't recurse into it
                            continue

                        local_hierarchy[curr_str].append(str(entry_path))
                        child_depth = depth + 1
                        if self.depth is None or child_depth <= self.depth:
                            subfolders.append((entry_path, child_depth))
                    else:
                        try:
                            st = entry.stat(follow_symlinks=self.follow_links)
                            size = int(st.st_size)
                            mtime = float(st.st_mtime)
                        except Exception:
                            continue

                        if not self._passes_mtime(mtime):
                            continue
                        if self.extensions_filter is not None:
                            if entry_path.suffix.lower() not in self.extensions_filter:
                                continue
                        if self.query_re is not None and not self.query_re.search(entry_path.name):
                            continue
                        if self.min_size and size < self.min_size:
                            continue
                        if self.max_size and size > self.max_size:
                            continue

                        local_files_size += size
                        file_count += 1

                        file_info = EntryInfo(entry_path, is_dir=False, size=size)
                        file_info.modified = mtime
                        results.files.append(file_info)
                        ext = entry_path.suffix.lower()
                        if ext:
                            results.extensions.add(ext)

                        if self.include_files and not self.folders_only:
                            results.entries[str(entry_path)] = file_info

                except Exception:
                    continue

            local_files_sizes[curr_str] = local_files_size
            return folder_count, file_count, subfolders, local_files_sizes, local_hierarchy

        try:
            with progress:
                # We use a thread pool to run scandir on many directories in parallel.
                # The pool schedules walks; each walk returns its subfolders which
                # we then re-submit. This is a classic work-stealing traversal.
                with ThreadPoolExecutor(max_workers=self.workers) as pool:
                    in_flight: Dict = {}
                    # Submit root
                    fut = pool.submit(_walk, self.root_path, 0)
                    in_flight[fut] = (self.root_path, 0)

                    while in_flight:
                        try:
                            done_iter = list(as_completed(
                                list(in_flight.keys()), timeout=None))
                        except KeyboardInterrupt:
                            # Flip the flag so in-flight workers wind down,
                            # then let the context managers clean up.
                            self._cancelled = True
                            raise

                        for fut in done_iter:
                            parent_path, parent_depth = in_flight.pop(fut)
                            try:
                                folder_count, file_count, subfolders, lfs, lh = fut.result()
                            except Exception:
                                continue

                            results.folders_scanned += folder_count
                            results.files_scanned += file_count
                            if parent_depth > results.max_depth_reached:
                                results.max_depth_reached = parent_depth
                            all_folders.append((parent_path, parent_depth))
                            for k, v in lfs.items():
                                folder_files_sizes[k] = folder_files_sizes.get(k, 0) + v
                            for k, v in lh.items():
                                results.hierarchy[k] = results.hierarchy.get(k, []) + v

                            progress.update(results.folders_scanned, results.files_scanned)

                            for sub_path, sub_depth in subfolders:
                                fut2 = pool.submit(_walk, sub_path, sub_depth)
                                in_flight[fut2] = (sub_path, sub_depth)

            # If the root was unreadable, raise so the CLI can return exit code 2
            if root_blocked_error:
                raise root_blocked_error[0]
        except KeyboardInterrupt:
            # Record partial results so the CLI can decide what to do.
            self._cancelled = True
            try:
                # Shut the spinner down cleanly so we don't leave a partial
                # line on stderr.
                progress.__exit__(None, None, None)
            except Exception:
                pass
            try:
                # Persist whatever we already accumulated for size roll-up.
                for folder_path, folder_depth in all_folders:
                    path_str = str(folder_path)
                    total_folder_size = folder_files_sizes.get(path_str, 0)
                    for child_path_str in results.hierarchy.get(path_str, []):
                        child_info = results.entries.get(child_path_str)
                        if child_info and child_info.is_dir:
                            total_folder_size += child_info.size
                    folder_info = EntryInfo(folder_path, is_dir=True,
                                            size=total_folder_size)
                    if not self.folders_only:
                        if total_folder_size >= self.min_size and (
                            self.max_size == 0 or total_folder_size <= self.max_size
                        ):
                            results.entries[path_str] = folder_info
                    else:
                        results.entries[path_str] = folder_info
                root_info = results.entries.get(str(self.root_path))
                if root_info:
                    results.total_size = root_info.size
                else:
                    results.total_size = sum(f.size for f in results.files)
                results.elapsed_time = time.time() - start
            except Exception:
                pass
            from spacelyzer.exceptions import UserCancelledException
            raise UserCancelledException(
                "Scan cancelled by user (Ctrl+C)."
            ) from None

        # Phase 2 — accumulate folder sizes bottom-up
        all_folders.sort(key=lambda x: x[1], reverse=True)
        for folder_path, folder_depth in all_folders:
            path_str = str(folder_path)
            total_folder_size = folder_files_sizes.get(path_str, 0)
            for child_path_str in results.hierarchy.get(path_str, []):
                child_info = results.entries.get(child_path_str)
                if child_info and child_info.is_dir:
                    total_folder_size += child_info.size

            folder_info = EntryInfo(folder_path, is_dir=True, size=total_folder_size)

            if not self.folders_only:
                if total_folder_size >= self.min_size and (
                    self.max_size == 0 or total_folder_size <= self.max_size
                ):
                    results.entries[path_str] = folder_info
            else:
                results.entries[path_str] = folder_info

        # Root totals
        root_info = results.entries.get(str(self.root_path))
        if root_info:
            results.total_size = root_info.size
        else:
            results.total_size = sum(f.size for f in results.files)

        # Phase 3 — final aggregations
        self._finalize(results, start)
        return results

    # ------------------------------------------------------------------ #
    def _finalize(self, results: ScanResults, start_time: float) -> None:
        """Compute aggregates consumed by renderers.

        Aggregation rules (avoids double-counting):

        * **Smart-skipped folders** — counted at their full summary size
          (their contents were not enumerated as files).
        * **Regular folders** — *not* added to category / age totals;
          their file contents are already accounted for via
          ``results.files``.
        * **Files** — always added individually.
        """
        from spacelyzer.analyzer import analyze_entry, age_bucket

        now = time.time()
        cat_sizes: Dict[str, int] = {}
        ext_sizes: Dict[str, int] = {}
        ext_counts: Dict[str, int] = {}
        age_sizes: Dict[str, int] = {}
        age_counts: Dict[str, int] = {}

        for path_str, entry in results.entries.items():
            if entry.size <= 0:
                continue
            _, category, _, _ = analyze_entry(entry.path, entry.is_dir)
            # Only smart-summarized folders contribute their aggregated
            # size — every other folder's bytes are already counted via
            # the files below, so adding them again would inflate totals
            # and push category percentages above 100%.
            if getattr(entry, "_smart_summary", False):
                cat_sizes[category] = cat_sizes.get(category, 0) + entry.size
                if entry.is_dir:
                    bucket = age_bucket(entry.modified, now)
                    age_sizes[bucket] = age_sizes.get(bucket, 0) + entry.size
                    age_counts[bucket] = age_counts.get(bucket, 0) + 1
            elif entry.is_dir:
                # Regular (recursed) folder — record its age only, do
                # NOT add size to category totals.
                bucket = age_bucket(entry.modified, now)
                age_sizes[bucket] = age_sizes.get(bucket, 0) + entry.size
                age_counts[bucket] = age_counts.get(bucket, 0) + 1
            else:
                # File inside ``entries`` (only present when ``--files``)
                cat_sizes[category] = cat_sizes.get(category, 0) + entry.size

        for f in results.files:
            ext = f.path.suffix.lower() or "(none)"
            ext_sizes[ext] = ext_sizes.get(ext, 0) + f.size
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
            _, category, _, _ = analyze_entry(f.path, False)
            if category:
                cat_sizes[category] = cat_sizes.get(category, 0) + f.size
            bucket = age_bucket(f.modified, now)
            age_sizes[bucket] = age_sizes.get(bucket, 0) + f.size
            age_counts[bucket] = age_counts.get(bucket, 0) + 1

        results.category_sizes = cat_sizes
        results.extension_stats = {
            ext: (ext_sizes[ext], ext_counts[ext]) for ext in ext_sizes
        }
        results.age_buckets = {
            bucket: (age_sizes[bucket], age_counts[bucket]) for bucket in age_sizes
        }
        results.largest_files = sorted(
            results.files, key=lambda x: x.size, reverse=True
        )[:50]

        if results.files:
            sizes = sorted(f.size for f in results.files)
            n = len(sizes)
            results.avg_file_size = sum(sizes) / n
            mid = n // 2
            results.median_file_size = (
                sizes[mid] if n % 2 else (sizes[mid - 1] + sizes[mid]) / 2
            )

        results.elapsed_time = time.time() - start_time


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def _glob_to_regex(pattern: str) -> str:
    """Translate a .gitignore-style glob to a regex matching the basename."""
    i, n = 0, len(pattern)
    out = ["^"]
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                out.append(".*")
                i += 2
                # Eat trailing slash if present
                if i < n and pattern[i] == "/":
                    i += 1
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            j = i + 1
            while j < n and pattern[j] != "]":
                j += 1
            if j >= n:
                out.append(re.escape("["))
                i += 1
            else:
                out.append(pattern[i:j + 1])
                i = j + 1
        elif c in ".+(){}|^$/\\":
            out.append(re.escape(c))
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    out.append("$")
    return "".join(out)