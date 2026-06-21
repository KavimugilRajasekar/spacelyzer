from typing import Dict, List, Tuple, Any
from spacelyzer.scanner import EntryInfo
from spacelyzer.analyzer import KNOWN_FOLDERS

class SuggestionItem:
    def __init__(self, key: str, label: str, count: int, total_size: int):
        self.key = key
        self.label = label
        self.count = count
        self.total_size = total_size

class SuggestionsAnalyzer:
    def __init__(self, entries: Dict[str, EntryInfo], duplicate_groups: List[Tuple[str, List[EntryInfo]]]):
        self.entries = entries
        self.duplicate_groups = duplicate_groups

    def generate_suggestions(self) -> List[SuggestionItem]:
        """Aggregate reclaimable files/folders into actionable suggestion items."""
        suggestions_map = {
            'node_modules': {'label': 'node_modules folders', 'count': 0, 'size': 0},
            'pycache': {'label': '__pycache__ folders', 'count': 0, 'size': 0},
            'build': {'label': 'build/dist folders', 'count': 0, 'size': 0},
            'temp': {'label': 'temporary folders', 'count': 0, 'size': 0},
            'duplicates': {'label': 'duplicate files', 'count': 0, 'size': 0}
        }

        # Analyze folders
        for path_str, entry in self.entries.items():
            if not entry.is_dir:
                continue
            
            name = entry.name
            if name == 'node_modules':
                suggestions_map['node_modules']['count'] += 1
                suggestions_map['node_modules']['size'] += entry.size
            elif name in ('__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache'):
                suggestions_map['pycache']['count'] += 1
                suggestions_map['pycache']['size'] += entry.size
            elif name in ('build', 'dist', 'target', '.next', '.nuxt', 'bin', 'obj'):
                suggestions_map['build']['count'] += 1
                suggestions_map['build']['size'] += entry.size
            elif name in ('tmp', 'temp', 'Temp', '.cache'):
                suggestions_map['temp']['count'] += 1
                suggestions_map['temp']['size'] += entry.size

        # Analyze duplicates
        for name, files in self.duplicate_groups:
            # If we have N duplicates, we keep 1, meaning N-1 are reclaimable.
            if len(files) > 1:
                reclaimable_count = len(files) - 1
                reclaimable_size = sum(f.size for f in files[1:]) # Skip the first copy
                suggestions_map['duplicates']['count'] += reclaimable_count
                suggestions_map['duplicates']['size'] += reclaimable_size

        items = []
        for key, val in suggestions_map.items():
            if val['count'] > 0:
                items.append(SuggestionItem(
                    key=key,
                    label=val['label'],
                    count=val['count'],
                    total_size=val['size']
                ))
        
        # Sort suggestions by largest reclaimable size descending
        items.sort(key=lambda x: x.total_size, reverse=True)
        return items
