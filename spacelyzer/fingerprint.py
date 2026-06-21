from typing import Dict, List, Tuple
from spacelyzer.scanner import EntryInfo
from spacelyzer.analyzer import EXTENSION_CATEGORIES

class FingerprintCategory:
    def __init__(self, name: str, size: int = 0):
        self.name = name
        self.size = size

class StorageFingerprinter:
    def __init__(self, entries: Dict[str, EntryInfo], files: List[EntryInfo]):
        self.entries = entries
        self.files = files

    def get_fingerprints(self) -> List[FingerprintCategory]:
        """Classify files/folders to determine the user's storage fingerprint."""
        classifications = {
            'JavaScript Development': 0,
            'Python Development': 0,
            'Rust Projects': 0,
            'Android Development': 0,
            'Docker Data': 0,
            'Media Library': 0,
            'Archives': 0
        }

        # Scan folders to assign size to specific development environments
        for path_str, entry in self.entries.items():
            if not entry.is_dir:
                continue
            
            name = entry.name
            if name == 'node_modules':
                classifications['JavaScript Development'] += entry.size
            elif name in ('venv', '.venv', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache'):
                classifications['Python Development'] += entry.size
            elif name == 'target':
                classifications['Rust Projects'] += entry.size
            elif name in ('.gradle', 'Android', 'AndroidStudio'):
                classifications['Android Development'] += entry.size
            elif 'docker' in name.lower() or '.docker' in name.lower():
                classifications['Docker Data'] += entry.size

        # Scan files for Media and Archives
        for f in self.files:
            ext = f.path.suffix.lower()
            category = EXTENSION_CATEGORIES.get(ext)
            if category == 'Media':
                classifications['Media Library'] += f.size
            elif category == 'Archive':
                classifications['Archives'] += f.size

        fingerprints = [
            FingerprintCategory(name=k, size=v)
            for k, v in classifications.items()
            if v > 0
        ]
        # Sort by size descending
        fingerprints.sort(key=lambda x: x.size, reverse=True)
        return fingerprints
