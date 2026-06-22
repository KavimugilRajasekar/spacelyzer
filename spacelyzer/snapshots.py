"""
Snapshot persistence and comparison.

Spacelyzer stores snapshots in ``~/.spacelyzer/snapshots/`` as JSON files.
Each file is named after the scanned root + a timestamp so the user can
diff today's scan against one from a week ago and see exactly what grew,
what shrank, and what appeared/disappeared.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spacelyzer.scanner import ScanResults


SNAPSHOT_DIR = Path.home() / ".spacelyzer" / "snapshots"


def ensure_snapshot_dir() -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return SNAPSHOT_DIR


# --------------------------------------------------------------------------- #
#  Snapshot data model
# --------------------------------------------------------------------------- #
@dataclass
class Snapshot:
    """Serializable view of a scan."""
    path: str
    scanned_at: float
    elapsed_seconds: float
    total_size: int
    folders_scanned: int
    files_scanned: int
    max_depth_reached: int
    extensions: List[str] = field(default_factory=list)
    entries: List[Tuple[str, int, bool, float]] = field(default_factory=list)
    # (path, size, is_dir, mtime)
    files: List[Tuple[str, int, float]] = field(default_factory=list)
    # (path, size, mtime)
    category_sizes: Dict[str, int] = field(default_factory=dict)
    extension_stats: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    age_buckets: Dict[str, Tuple[int, int]] = field(default_factory=dict)

    @classmethod
    def from_results(cls, results: ScanResults, scanned_at: Optional[float] = None) -> "Snapshot":
        return cls(
            path=str(results.root_path),
            scanned_at=scanned_at or time.time(),
            elapsed_seconds=round(results.elapsed_time, 3),
            total_size=results.total_size,
            folders_scanned=results.folders_scanned,
            files_scanned=results.files_scanned,
            max_depth_reached=results.max_depth_reached,
            extensions=sorted(results.extensions),
            entries=[
                (str(p), e.size, bool(e.is_dir), float(e.modified))
                for p, e in results.entries.items()
            ],
            files=[
                (str(f.path), f.size, float(f.modified)) for f in results.files
            ],
            category_sizes=dict(results.category_sizes),
            extension_stats={
                k: (v[0], v[1]) for k, v in results.extension_stats.items()
            },
            age_buckets={k: (v[0], v[1]) for k, v in results.age_buckets.items()},
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Snapshot":
        return cls(
            path=d["path"],
            scanned_at=d["scanned_at"],
            elapsed_seconds=d["elapsed_seconds"],
            total_size=d["total_size"],
            folders_scanned=d["folders_scanned"],
            files_scanned=d["files_scanned"],
            max_depth_reached=d["max_depth_reached"],
            extensions=list(d.get("extensions", [])),
            entries=[tuple(x) for x in d.get("entries", [])],
            files=[tuple(x) for x in d.get("files", [])],
            category_sizes=dict(d.get("category_sizes", {})),
            extension_stats={
                k: tuple(v) for k, v in d.get("extension_stats", {}).items()
            },
            age_buckets={k: tuple(v) for k, v in d.get("age_buckets", {}).items()},
        )


def save_snapshot(results: ScanResults, label: Optional[str] = None) -> Path:
    """Write a snapshot to disk; return the resulting path."""
    ensure_snapshot_dir()
    snap = Snapshot.from_results(results)
    ts = time.strftime("%Y%m%d-%H%M%S", time.localtime(snap.scanned_at))
    safe_root = _safe_name(snap.path)
    name = f"{safe_root}__{ts}.json"
    if label:
        name = f"{_safe_name(label)}__{ts}.json"
    path = SNAPSHOT_DIR / name
    path.write_text(json.dumps(snap.to_dict(), indent=2), encoding="utf-8")
    return path


def load_snapshot(path: Path) -> Snapshot:
    return Snapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))


def list_snapshots(root_path: Optional[str] = None) -> List[Path]:
    ensure_snapshot_dir()
    all_files = sorted(SNAPSHOT_DIR.glob("*.json"), key=lambda p: p.name)
    files = sorted(all_files, key=lambda p: p.stat().st_mtime, reverse=True)
    if not root_path:
        return files
    safe = _safe_name(root_path)
    return [p for p in files if p.name.startswith(safe + "__")]


def delete_snapshot(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def _safe_name(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s)[:80]


# --------------------------------------------------------------------------- #
#  Diff
# --------------------------------------------------------------------------- #
@dataclass
class DiffEntry:
    path: str
    old_size: Optional[int]
    new_size: Optional[int]

    @property
    def delta(self) -> int:
        a = self.new_size or 0
        b = self.old_size or 0
        return a - b

    @property
    def status(self) -> str:
        if self.old_size is None:
            return "added"
        if self.new_size is None:
            return "removed"
        if self.delta > 0:
            return "grown"
        if self.delta < 0:
            return "shrunk"
        return "unchanged"


@dataclass
class Diff:
    old: Snapshot
    new: Snapshot
    entries: List[DiffEntry]
    old_total: int
    new_total: int
    file_count_delta: int

    @property
    def total_delta(self) -> int:
        return self.new_total - self.old_total


def diff_snapshots(old: Snapshot, new: Snapshot) -> Diff:
    old_map: Dict[str, int] = {p: s for p, s, _d, _m in old.entries}
    new_map: Dict[str, int] = {p: s for p, s, _d, _m in new.entries}

    paths = set(old_map) | set(new_map)
    entries: List[DiffEntry] = []
    for p in paths:
        entries.append(DiffEntry(
            path=p,
            old_size=old_map.get(p),
            new_size=new_map.get(p),
        ))

    entries.sort(key=lambda e: abs(e.delta), reverse=True)
    return Diff(
        old=old,
        new=new,
        entries=entries,
        old_total=old.total_size,
        new_total=new.total_size,
        file_count_delta=new.files_scanned - old.files_scanned,
    )