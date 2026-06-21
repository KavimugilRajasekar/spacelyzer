import os
import sys
import time
import fnmatch
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple, Any
from spacelyzer.exceptions import PermissionDeniedException, PathNotFoundException
from spacelyzer.formatter import has_unicode_support


class EntryInfo:
    def __init__(self, path: Path, is_dir: bool, size: int = 0):
        self.path = path
        self.is_dir = is_dir
        self.size = size
        self.name = path.name if path.name else str(path)
        self.modified = 0.0
        try:
            stat_result = path.symlink_metadata() if not path.is_symlink() else path.lstat()
            self.modified = stat_result.st_mtime
        except Exception:
            pass

class ScanResults:
    def __init__(self, root_path: Path):
        self.root_path = root_path
        self.total_size = 0
        self.folders_scanned = 0
        self.files_scanned = 0
        self.elapsed_time = 0.0
        self.max_depth_reached = 0          # deepest level actually traversed
        # Maps absolute path string to EntryInfo
        self.entries: Dict[str, EntryInfo] = {}
        # Stores parent-child relationships for hierarchical tree building
        # parent_path -> list of child_paths
        self.hierarchy: Dict[str, List[str]] = {}
        # Keep list of files separately for duplicate/largest-files analysis
        self.files: List[EntryInfo] = []
        # Set of unique extensions
        self.extensions: Set[str] = set()

class DiskScanner:
    def __init__(
        self,
        root_path: str,
        depth: Optional[int] = None,
        include_files: bool = False,
        folders_only: bool = False,
        include_hidden: bool = False,
        follow_links: bool = False,
        ignore_patterns: Optional[List[str]] = None,
        min_size: int = 0
    ):
        self.root_path = Path(root_path).resolve()
        self.depth = depth
        self.include_files = include_files
        self.folders_only = folders_only
        self.include_hidden = include_hidden
        self.follow_links = follow_links
        self.ignore_patterns = ignore_patterns or []
        self.min_size = min_size
        # Windows pseudo-folders: always inaccessible and add no value
        self._win_skip_names: set = {
            'System Volume Information',
            '$Recycle.Bin',
            '$RECYCLE.BIN',
            '$WinREAgent',
            '$WINDOWS.~BT',
            '$WINDOWS.~WS',
            'Recovery',
            'DumpStack.log.tmp',
        } if os.name == 'nt' else set()
        
        if not self.root_path.exists():
            raise PathNotFoundException(f"Path not found: {root_path}")
            
    def _is_hidden(self, path: Path) -> bool:
        """Check if file or folder is hidden."""
        if path.name.startswith('.'):
            return True
        # Windows specific check
        if os.name == 'nt':
            try:
                import stat
                attrs = path.stat().st_file_attributes
                return bool(attrs & stat.FILE_ATTRIBUTE_HIDDEN)
            except Exception:
                pass
        return False

    def _should_ignore(self, path: Path) -> bool:
        """Check if path matches any ignore patterns or is hidden (if hidden excluded)."""
        if not self.include_hidden and self._is_hidden(path):
            return True
            
        path_str = str(path)
        name = path.name
        
        for pattern in self.ignore_patterns:
            if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(path_str, pattern):
                return True
        return False

    def scan(self) -> ScanResults:
        """Traverse the filesystem and gather metadata."""
        start_time = time.time()
        results = ScanResults(self.root_path)
        
        # We perform a post-order or bottom-up summation of directory sizes.
        # But to be safe from recursion limit and to show a live progress bar,
        # we do a standard BFS/DFS iteration to find all directories and files,
        # and then compute folder sizes by summing up children.
        
        # Queue/stack of (current_dir_path, depth_level)
        stack: List[Tuple[Path, int]] = [(self.root_path, 0)]
        
        # Temporarily record folder sizes during traversal
        folder_files_sizes: Dict[str, int] = {}
        all_folders: List[Tuple[Path, int]] = []
        
        # Check stdout encoding unicode support
        has_unicode = has_unicode_support()

        spin_chars = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'] if has_unicode else ['|', '/', '-', '\\']
        bullet = '·' if has_unicode else '-'
        last_progress_time = 0.0
        
        try:
            while stack:
                curr_path, curr_depth = stack.pop()
                
                # Check cancellation
                # In Python, KeyboardInterrupt will automatically bubble up, but we catch it in cli.py
                
                # Print progress
                curr_time = time.time()
                if curr_time - last_progress_time > 0.1:
                    spin_idx = int(curr_time * 10) % len(spin_chars)
                    sys.stderr.write(
                        f"\rScanning...  {spin_chars[spin_idx]}  {bullet}  {results.folders_scanned:,} folders, {results.files_scanned:,} files scanned"
                    )
                    sys.stderr.flush()
                    last_progress_time = curr_time
                
                # Never ignore the root path itself (e.g. C:\ has hidden attrs on Windows)
                if curr_path != self.root_path and self._should_ignore(curr_path):
                    continue
                    
                if self.depth is not None and curr_depth > self.depth:
                    continue
                
                # Scan directory
                try:
                    entries = list(os.scandir(curr_path))
                except PermissionError as e:
                    if curr_path == self.root_path:
                        raise e
                    # Silently skip or note permission denied
                    continue
                except FileNotFoundError:
                    continue
                
                results.folders_scanned += 1
                if curr_depth > results.max_depth_reached:
                    results.max_depth_reached = curr_depth
                all_folders.append((curr_path, curr_depth))
                curr_path_str = str(curr_path)
                results.hierarchy[curr_path_str] = []
                
                local_files_size = 0
                for entry in entries:
                    try:
                        entry_path = Path(entry.path)
                        
                        if self._should_ignore(entry_path):
                            continue
                            
                        if entry.is_symlink() and not self.follow_links:
                            continue
                            
                        if entry.is_dir(follow_symlinks=self.follow_links):
                            # Skip Windows inaccessible pseudo-folders
                            if entry.name in self._win_skip_names:
                                continue
                            results.hierarchy[curr_path_str].append(str(entry_path))
                            # Only push if child depth is within the limit — avoids
                            # thousands of wasted push/pop cycles on large drives
                            child_depth = curr_depth + 1
                            if self.depth is None or child_depth <= self.depth:
                                stack.append((entry_path, child_depth))
                        else:
                            # It's a file
                            size = entry.stat().st_size
                            local_files_size += size
                            results.files_scanned += 1
                            
                            file_info = EntryInfo(entry_path, is_dir=False, size=size)
                            results.files.append(file_info)
                            
                            # Log extension
                            ext = entry_path.suffix.lower()
                            if ext:
                                results.extensions.add(ext)
                                
                            if self.include_files and not self.folders_only:
                                results.entries[str(entry_path)] = file_info
                                
                    except Exception:
                        continue
                
                folder_files_sizes[curr_path_str] = local_files_size
                
        finally:
            # Clear progress indicator line
            sys.stderr.write("\r" + " " * 80 + "\r")
            sys.stderr.flush()
            
        # Calculate cumulative size of directories from bottom up
        # Sort folders by depth in descending order so children are calculated before parents
        all_folders.sort(key=lambda x: x[1], reverse=True)
        
        for folder_path, folder_depth in all_folders:
            path_str = str(folder_path)
            # Size of files directly in this folder
            total_folder_size = folder_files_sizes.get(path_str, 0)
            
            # Plus size of subdirectories
            for child_path_str in results.hierarchy.get(path_str, []):
                child_info = results.entries.get(child_path_str)
                if child_info and child_info.is_dir:
                    total_folder_size += child_info.size
            
            folder_info = EntryInfo(folder_path, is_dir=True, size=total_folder_size)
            
            # Store folder if we aren't filtering folder output
            if not self.include_files or not self.folders_only:
                # If we filter folders based on min_size, do it here or during render?
                # The --min filter applies to the returned results
                if total_folder_size >= self.min_size:
                    results.entries[path_str] = folder_info
            else:
                # Still store folder size so parents can accumulate, but maybe don't display it.
                # Actually, results.entries holds entries that will be listed.
                results.entries[path_str] = folder_info
                
        # Total size of the root path
        root_info = results.entries.get(str(self.root_path))
        if root_info:
            results.total_size = root_info.size
        else:
            # Fallback if root path is empty or not scanned
            results.total_size = sum(f.size for f in results.files)
            
        results.elapsed_time = time.time() - start_time
        return results
