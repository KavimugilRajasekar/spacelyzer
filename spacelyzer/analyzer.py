import os
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

# Maps folder names to: (Reason Label, Category, Icon)
KNOWN_FOLDERS = {
    'node_modules': ('Node Modules', 'Dependency', ''),
    '__pycache__': ('Python Cache', 'Cache', ''),
    '.pytest_cache': ('Pytest Cache', 'Cache', ''),
    '.mypy_cache': ('MyPy Cache', 'Cache', ''),
    '.ruff_cache': ('Ruff Cache', 'Cache', ''),
    '.next': ('Next.js Build', 'Build', ''),
    '.nuxt': ('Nuxt Build', 'Build', ''),
    'dist': ('Build Output', 'Build', ''),
    'build': ('Build Output', 'Build', ''),
    'target': ('Rust Build', 'Build', ''),
    'bin': ('Compiled Binaries', 'Build', ''),
    'obj': ('Object Files', 'Build', ''),
    '.gradle': ('Gradle Cache', 'Cache', ''),
    '.idea': ('IDE Metadata', 'IDE Metadata', ''),
    '.vscode': ('Workspace Settings', 'IDE Metadata', ''),
    'venv': ('Python Virtualenv', 'Virtual Environment', ''),
    '.venv': ('Python Virtualenv', 'Virtual Environment', ''),
    'env': ('Python Environment', 'Virtual Environment', ''),
    'Pods': ('CocoaPods', 'Dependency', ''),
    'DerivedData': ('Xcode Cache', 'Cache', ''),
    '.terraform': ('Terraform Cache', 'Cache', ''),
    '.cache': ('General Cache', 'Cache', ''),
    'tmp': ('Temporary Files', 'Temporary', ''),
    'temp': ('Temporary Files', 'Temporary', ''),
    'Temp': ('Temporary Files', 'Temporary', '')
}

# Maps extensions to category
EXTENSION_CATEGORIES = {
    # Media
    '.mp4': 'Media', '.mkv': 'Media', '.avi': 'Media', '.mov': 'Media', '.wmv': 'Media',
    '.flv': 'Media', '.webm': 'Media', '.mpg': 'Media', '.mpeg': 'Media', '.m4v': 'Media',
    '.mp3': 'Media', '.wav': 'Media', '.flac': 'Media', '.m4a': 'Media', '.aac': 'Media',
    '.ogg': 'Media', '.png': 'Media', '.jpg': 'Media', '.jpeg': 'Media', '.gif': 'Media',
    '.bmp': 'Media', '.svg': 'Media', '.tiff': 'Media', '.webp': 'Media', '.ico': 'Media',
    # Archive
    '.zip': 'Archive', '.tar': 'Archive', '.gz': 'Archive', '.rar': 'Archive',
    '.7z': 'Archive', '.bz2': 'Archive', '.xz': 'Archive', '.iso': 'Archive',
    '.dmg': 'Archive', '.tgz': 'Archive',
    # Documents
    '.pdf': 'Documents', '.docx': 'Documents', '.xlsx': 'Documents', '.pptx': 'Documents',
    '.doc': 'Documents', '.xls': 'Documents', '.ppt': 'Documents', '.txt': 'Documents',
    '.rtf': 'Documents', '.odt': 'Documents', '.ods': 'Documents', '.odp': 'Documents',
    '.csv': 'Documents', '.md': 'Documents',
    # Source Code
    '.js': 'Source Code', '.py': 'Source Code', '.rs': 'Source Code', '.java': 'Source Code',
    '.cpp': 'Source Code', '.c': 'Source Code', '.h': 'Source Code', '.ts': 'Source Code',
    '.html': 'Source Code', '.css': 'Source Code', '.go': 'Source Code', '.rb': 'Source Code',
    '.php': 'Source Code', '.kt': 'Source Code', '.cs': 'Source Code', '.sh': 'Source Code',
    '.json': 'Source Code', '.xml': 'Source Code', '.yaml': 'Source Code', '.yml': 'Source Code',
    '.sql': 'Source Code', '.pl': 'Source Code', '.swift': 'Source Code', '.m': 'Source Code',
}

SYSTEM_FOLDERS_WINDOWS = {'windows', 'program files', 'program files (x86)', 'users', 'system32'}
SYSTEM_FOLDERS_UNIX = {'library', 'applications', 'etc', 'usr', 'bin', 'sys', 'proc', 'dev', 'var', 'sbin', 'root'}

def get_safety_status(path: Path) -> Optional[str]:
    """Check if the directory is a system-critical folder that shouldn't be touched."""
    path_name_lower = path.name.lower()
    
    if os.name == 'nt':
        # On Windows, check against system folders or if it's the root system drive
        if path_name_lower in SYSTEM_FOLDERS_WINDOWS:
            return 'SYSTEM'
    else:
        # On Unix/macOS, check parts
        if path_name_lower in SYSTEM_FOLDERS_UNIX:
            return 'SYSTEM'
        # Check absolute path prefix for Unix system areas
        path_str = str(path.resolve())
        for sys_dir in ['/usr', '/etc', '/bin', '/sys', '/proc', '/dev', '/var', '/sbin', '/system', '/library', '/applications']:
            if path_str.startswith(sys_dir):
                return 'SYSTEM'
                
    return None

def analyze_entry(path: Path, is_dir: bool) -> Tuple[str, str, str, Optional[str]]:
    """
    Returns (Reason Label, Category, Icon, Safety Status) for any file or directory.
    """
    safety = get_safety_status(path)
    
    if is_dir:
        name = path.name
        if name in KNOWN_FOLDERS:
            reason, category, icon = KNOWN_FOLDERS[name]
            return reason, category, icon, safety
        
        # Check for system flag
        if safety == 'SYSTEM':
            return 'System Root', 'SYSTEM', '', safety
            
        return '—', 'Unknown', '', safety
    else:
        # File analysis
        ext = path.suffix.lower()
        if ext in EXTENSION_CATEGORIES:
            category = EXTENSION_CATEGORIES[ext]
            # Simple icon mapping per category
            icons = {
                'Media': '',
                'Archive': '',
                'Documents': '',
                'Source Code': '',
            }
            icon = icons.get(category, '')
            return '—', category, icon, safety
            
        return '—', 'Unknown', '', safety
