"""
Intelligent suggestions analyzer.

The original version recognized five reclaimable patterns. The enhanced
version recognizes many more and also surfaces per-pattern worst-offender
paths so the user can take action immediately.
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from spacelyzer.scanner import EntryInfo


class SuggestionItem:
    __slots__ = ("key", "label", "count", "total_size", "top_paths", "category")

    def __init__(
        self,
        key: str,
        label: str,
        count: int,
        total_size: int,
        top_paths: Sequence[Tuple[str, int]],
        category: str = "Reclaimable",
    ):
        self.key = key
        self.label = label
        self.count = count
        self.total_size = total_size
        self.top_paths = list(top_paths)
        self.category = category


# Each rule:
#   key      : identifier (also used in JSON)
#   label    : human label printed by the suggestions section
#   category : Pillar-4 semantic category
#   match    : set of folder basenames that count
_RULES: List[Tuple[str, str, str, Tuple[str, ...]]] = [
    ("node_modules", "node_modules folders", "Dependency",
     ("node_modules",)),
    ("pycache", "Python cache folders", "Cache",
     ("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache")),
    ("build", "Build/output folders", "Build",
     ("build", "dist", "target", ".next", ".nuxt", "out", "release",
      "obj", "bin")),
    ("venv", "Python virtualenvs", "Virtual Environment",
     ("venv", ".venv", "env", ".tox", ".nox")),
    ("temp", "Temporary folders", "Temporary",
     ("tmp", "temp", "Temp", ".cache", "cache")),
    ("logs", "Log folders", "Logs",
     ("logs", ".logs")),
    ("cocoapods", "CocoaPods folders", "Dependency",
     ("Pods",)),
    ("xcode", "Xcode DerivedData", "Cache",
     ("DerivedData",)),
    ("gradle", "Gradle cache folders", "Cache",
     (".gradle",)),
    ("terraform", "Terraform state", "Cache",
     (".terraform",)),
    ("ide", "IDE workspace settings", "IDE Metadata",
     (".idea", ".vscode")),
    ("parcel", "Parcel/Turbo cache", "Cache",
     (".parcel-cache", ".turbo")),
    ("yarn", "Yarn cache folders", "Cache",
     (".yarn", ".pnpm-store")),
]


class SuggestionsAnalyzer:
    def __init__(
        self,
        entries: Dict[str, EntryInfo],
        duplicate_groups: Sequence[Tuple[str, List[EntryInfo]]],
        top_per_rule: int = 5,
    ):
        self.entries = entries
        self.duplicate_groups = duplicate_groups
        self.top_per_rule = top_per_rule

    def generate_suggestions(self) -> List[SuggestionItem]:
        """Build the reclaimable-spaces suggestion list."""
        matches: Dict[str, Dict[str, object]] = {}

        for path_str, entry in self.entries.items():
            if not entry.is_dir:
                continue
            name = entry.name
            for key, label, category, basenames in _RULES:
                if name in basenames:
                    bucket = matches.setdefault(
                        key,
                        {"label": label, "category": category,
                         "count": 0, "size": 0, "paths": []},
                    )
                    bucket["count"] += 1
                    bucket["size"] += entry.size
                    bucket["paths"].append((str(entry.path), entry.size))

        # Duplicate file reclaimable space: N copies → keep 1
        dup_count = 0
        dup_size = 0
        for _, group in self.duplicate_groups:
            if len(group) > 1:
                dup_count += len(group) - 1
                dup_size += sum(f.size for f in sorted(group, key=lambda x: x.size, reverse=True)[1:])
        if dup_count > 0:
            matches["duplicates"] = {
                "label": "duplicate files (keep 1 copy)",
                "category": "Duplicates",
                "count": dup_count,
                "size": dup_size,
                "paths": [(str(g[0].path), sum(f.size for f in g)) for _, g in self.duplicate_groups],
            }

        items: List[SuggestionItem] = []
        for key, info in matches.items():
            count = int(info["count"])
            if count <= 0:
                continue
            # Sort top_paths alphabetically by path name first, then by size descending
            paths_sorted = sorted(info["paths"], key=lambda x: x[0].lower())
            top_paths = sorted(paths_sorted, key=lambda x: x[1], reverse=True)[
                : self.top_per_rule
            ]
            items.append(SuggestionItem(
                key=key,
                label=str(info["label"]),
                count=count,
                total_size=int(info["size"]),
                top_paths=top_paths,
                category=str(info["category"]),
            ))

        # Stably sort suggestions alphabetically by label first, then by total size descending
        items.sort(key=lambda x: x.label.lower())
        items.sort(key=lambda x: x.total_size, reverse=True)
        return items