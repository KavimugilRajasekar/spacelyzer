"""
Similarity & duplicate detection.

Algorithms
----------
1. **Exact duplicates** — by default we use BLAKE2b-256 (≈3× faster than
   SHA-256 on large files, cryptographically strong enough for content
   addressing). For each file, we hash:
     (a) size         — the cheapest filter
     (b) first 64 KiB — a quick reject for files of equal size
     (c) full BLAKE2b — only when (a) and (b) match
   This makes dedup dramatically faster on huge folders with a few
   common sizes.
2. **Similar files** — same basename + ±10 % size tolerance.
3. **Similar folders** — same folder name appearing in multiple locations.

A CLI flag (`--hash sha256`) lets the user force the legacy SHA-256 if
needed for cross-tool compatibility.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from spacelyzer.scanner import EntryInfo


# --------------------------------------------------------------------------- #
#  Hashing
# --------------------------------------------------------------------------- #
_HASH_CHUNK = 1 << 16        # 64 KiB read buffer
_PARTIAL_CHUNK = 1 << 16     # bytes used for the "fast-reject" prefix hash


def _hash_stream(path: Path, algo: str, callback: Optional[Callable[[int], None]] = None) -> str:
    """Stream-hash *path*; *callback* gets called with bytes-hashed so far."""
    h = hashlib.new(algo)
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(_HASH_CHUNK)
                if not chunk:
                    break
                h.update(chunk)
                if callback is not None:
                    try:
                        callback(len(chunk))
                    except Exception:
                        pass
        return h.hexdigest()
    except Exception:
        # Permission denied, vanished file, etc. — fall back to a stable
        # pseudo-hash of the path so we don't crash the whole pass.
        return hashlib.sha1(str(path).encode("utf-8", "replace")).hexdigest()


def _partial_hash(path: Path, algo: str, limit: int = _PARTIAL_CHUNK) -> str:
    """Hash just the first *limit* bytes — fast reject."""
    h = hashlib.new(algo)
    try:
        with open(path, "rb") as f:
            data = f.read(limit)
        h.update(data)
        return h.hexdigest()
    except Exception:
        return ""


def get_file_hash(path: Path, algo: str = "blake2b") -> str:
    """Convenience wrapper used by tests / external callers."""
    return _hash_stream(path, algo)


# --------------------------------------------------------------------------- #
#  Detector
# --------------------------------------------------------------------------- #
class SimilarityDetector:
    def __init__(
        self,
        files: Sequence[EntryInfo],
        folders: Sequence[EntryInfo],
        hash_algo: str = "blake2b",
        workers: int = 0,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ):
        self.files = list(files)
        self.folders = list(folders)
        self.hash_algo = hash_algo
        self.workers = max(1, workers or min(16, (os_cpu_count() or 4)))
        self.progress_cb = progress_cb

    # ------------------------------------------------------------------ #
    #  Exact duplicates (full content hash)
    # ------------------------------------------------------------------ #
    def find_exact_duplicates(self) -> List[Tuple[str, List[EntryInfo]]]:
        """Return [(name, [EntryInfo, ...]), ...] for byte-identical file groups."""
        # 1) bucket by size
        size_groups: Dict[int, List[EntryInfo]] = defaultdict(list)
        for f in self.files:
            size_groups[f.size].append(f)

        candidates: List[EntryInfo] = []
        for size, group in size_groups.items():
            if len(group) >= 2 and size > 0:
                candidates.extend(group)

        if not candidates:
            return []

        # 2) bucket by partial-hash of first 64 KiB
        partial_groups: Dict[str, List[EntryInfo]] = defaultdict(list)
        for f in candidates:
            ph = _partial_hash(f.path, self.hash_algo)
            if not ph:
                continue
            partial_groups[ph].append(f)

        suspects: List[EntryInfo] = []
        for ph, group in partial_groups.items():
            if len(group) >= 2:
                suspects.extend(group)

        if not suspects:
            return []

        # 3) full hash, in parallel
        full_groups: Dict[str, List[EntryInfo]] = defaultdict(list)
        done = 0
        total = len(suspects)
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {
                pool.submit(_hash_stream, f.path, self.hash_algo): f
                for f in suspects
            }
            for fut in as_completed(futures):
                f = futures[fut]
                try:
                    digest = fut.result()
                except Exception:
                    continue
                full_groups[digest].append(f)
                done += 1
                if self.progress_cb is not None:
                    try:
                        self.progress_cb(done, total)
                    except Exception:
                        pass

        duplicates: List[Tuple[str, List[EntryInfo]]] = []
        for digest, group in full_groups.items():
            if len(group) > 1:
                # Stably sort: alphabetically by path first to break size ties
                group_sorted = sorted(group, key=lambda x: str(x.path).lower())
                group_sorted.sort(key=lambda x: x.size, reverse=True)
                duplicates.append((group_sorted[0].name, group_sorted))

        # Stably sort: alphabetically by group name first, then by reclaimable size descending
        duplicates.sort(key=lambda x: x[0].lower())
        duplicates.sort(key=lambda x: sum(f.size for f in x[1]) * (len(x[1]) - 1), reverse=True)
        return duplicates

    # ------------------------------------------------------------------ #
    #  Similar files (basename + size tolerance)
    # ------------------------------------------------------------------ #
    def find_similar_files(self) -> List[Tuple[str, List[EntryInfo]]]:
        name_groups: Dict[str, List[EntryInfo]] = defaultdict(list)
        for f in self.files:
            name_groups[f.name.lower()].append(f)

        similar: List[Tuple[str, List[EntryInfo]]] = []
        for name, group in name_groups.items():
            if len(group) < 2:
                continue
            group.sort(key=lambda x: x.size)

            visited = set()
            for i in range(len(group)):
                if i in visited:
                    continue
                cluster = [group[i]]
                visited.add(i)
                for j in range(i + 1, len(group)):
                    if j in visited:
                        continue
                    a, b = group[i].size, group[j].size
                    if a == 0 and b == 0:
                        # both empty
                        cluster.append(group[j])
                        visited.add(j)
                    elif a == 0 or b == 0:
                        continue
                    else:
                        diff = abs(a - b)
                        big = max(a, b)
                        if diff / big <= 0.10:
                            cluster.append(group[j])
                            visited.add(j)

                if len(cluster) > 1:
                    # Stably sort: alphabetically by path first to break size ties
                    cluster.sort(key=lambda x: str(x.path).lower())
                    cluster.sort(key=lambda x: x.size, reverse=True)
                    similar.append((cluster[0].name, cluster))

        # Stably sort: alphabetically by group name first, then by reclaimable size descending
        similar.sort(key=lambda x: x[0].lower())
        similar.sort(
            key=lambda x: sum(f.size for f in x[1]) * (len(x[1]) - 1), reverse=True
        )
        return similar

    # ------------------------------------------------------------------ #
    #  Similar folders (same name in multiple locations)
    # ------------------------------------------------------------------ #
    def find_similar_folders(self) -> List[Tuple[str, List[EntryInfo]]]:
        name_groups: Dict[str, List[EntryInfo]] = defaultdict(list)
        for folder in self.folders:
            if not folder.is_dir:
                continue
            name_groups[folder.name.lower()].append(folder)

        similar: List[Tuple[str, List[EntryInfo]]] = []
        for name, group in name_groups.items():
            if len(group) < 2:
                continue
            # Stably sort: alphabetically by path first to break size ties
            group.sort(key=lambda x: str(x.path).lower())
            group.sort(key=lambda x: x.size, reverse=True)
            similar.append((group[0].name, group))

        # Stably sort: alphabetically by group name first, then by reclaimable size descending
        similar.sort(key=lambda x: x[0].lower())
        similar.sort(
            key=lambda x: sum(f.size for f in x[1]) * (len(x[1]) - 1), reverse=True
        )
        return similar


def os_cpu_count() -> int:
    import os
    return os.cpu_count() or 4