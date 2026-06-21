import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple
from spacelyzer.scanner import EntryInfo

def get_file_sha256(path: Path) -> str:
    """Calculate SHA-256 hash of a file in chunks to minimize memory consumption."""
    sha256 = hashlib.sha256()
    try:
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                sha256.update(chunk)
        return sha256.hexdigest()
    except Exception:
        # If permission denied or other read error, return path string hash as fallback
        return hashlib.sha256(str(path).encode('utf-8')).hexdigest()

class SimilarityDetector:
    def __init__(self, files: List[EntryInfo], folders: List[EntryInfo]):
        self.files = files
        self.folders = folders

    def find_exact_duplicates(self) -> List[Tuple[str, List[EntryInfo]]]:
        """Find files with identical SHA-256 hashes."""
        # 1. Group by size first to avoid unnecessary hashing
        size_groups = defaultdict(list)
        for f in self.files:
            size_groups[f.size].append(f)

        # 2. For sizes with multiple files, compute hash
        hash_groups = defaultdict(list)
        for size, file_list in size_groups.items():
            if len(file_list) < 2:
                continue
            for f in file_list:
                file_hash = get_file_sha256(f.path)
                hash_groups[file_hash].append(f)

        # 3. Filter only groups with multiple entries
        duplicates = [
            (group[0].name, group)
            for file_hash, group in hash_groups.items()
            if len(group) > 1
        ]
        # Sort groups by total size of group descending
        duplicates.sort(key=lambda x: sum(f.size for f in x[1]), reverse=True)
        return duplicates

    def find_similar_files(self) -> List[Tuple[str, List[EntryInfo]]]:
        """Find files with the same name and extension, and size within +/- 10%."""
        # Group by filename (lowercase)
        name_groups = defaultdict(list)
        for f in self.files:
            name_groups[f.name.lower()].append(f)

        similar_groups = []
        for name, file_list in name_groups.items():
            if len(file_list) < 2:
                continue
            
            # Sort by size to make clustering easier
            file_list.sort(key=lambda x: x.size)
            
            # Cluster files whose sizes are within 10% of each other
            visited = set()
            for i in range(len(file_list)):
                if i in visited:
                    continue
                cluster = [file_list[i]]
                visited.add(i)
                for j in range(i + 1, len(file_list)):
                    if j in visited:
                        continue
                    # Check if size is within 10%
                    size_diff = abs(file_list[i].size - file_list[j].size)
                    max_size = max(file_list[i].size, file_list[j].size)
                    if max_size == 0 or (size_diff / max_size) <= 0.1:
                        cluster.append(file_list[j])
                        visited.add(j)
                
                if len(cluster) > 1:
                    similar_groups.append((cluster[0].name, cluster))

        # Sort by total size of the group descending
        similar_groups.sort(key=lambda x: sum(f.size for f in x[1]), reverse=True)
        return similar_groups

    def find_similar_folders(self) -> List[Tuple[str, List[EntryInfo]]]:
        """Find folders with the same name located in multiple locations."""
        name_groups = defaultdict(list)
        for folder in self.folders:
            name_groups[folder.name.lower()].append(folder)

        similar_folders = [
            (group[0].name, group)
            for name, group in name_groups.items()
            if len(group) > 1
        ]
        # Sort by total size of the group descending
        similar_folders.sort(key=lambda x: sum(f.size for f in x[1]), reverse=True)
        return similar_folders
