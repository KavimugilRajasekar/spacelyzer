"""
Pattern-based entry analyzer.

Classifies file/folder paths into:
  - reason (short human label)
  - category (semantic bucket used for grouping/summary)
  - icon (unicode emoji glyph, conditional on terminal support)
  - safety ('SYSTEM' for paths the user should never delete, otherwise None)

This module is pure-Python, has no I/O, and is safe to import in any context.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional, Tuple


# --------------------------------------------------------------------------- #
#  Known folder patterns
# --------------------------------------------------------------------------- #
#
# Tuple layout: (Reason Label, Category, Icon)
#
# Categories (stable, used as aggregation keys):
#   Dependency | Cache | Build | Virtual Environment | IDE Metadata |
#   Temporary | Logs | Media | Archive | Documents | Source Code |
#   Database | System | Unknown
#
KNOWN_FOLDERS: Dict[str, Tuple[str, str, str]] = {
    # ---- JavaScript / TypeScript
    "node_modules": ("Node Modules", "Dependency", "\U0001f4e6"),
    "bower_components": ("Bower Components", "Dependency", "\U0001f4e6"),
    "jspm_packages": ("JSPM Packages", "Dependency", "\U0001f4e6"),
    "pnpm-store": ("pnpm Store", "Dependency", "\U0001f4e6"),
    ".yarn": ("Yarn Cache", "Cache", "\U0001f4e6"),
    ".pnpm-store": ("pnpm Cache", "Cache", "\U0001f4e6"),
    # ---- Python
    "__pycache__": ("Python Cache", "Cache", "\U0001f40d"),
    ".pytest_cache": ("Pytest Cache", "Cache", "\U0001f40d"),
    ".mypy_cache": ("MyPy Cache", "Cache", "\U0001f40d"),
    ".ruff_cache": ("Ruff Cache", "Cache", "\U0001f40d"),
    ".tox": ("Tox Environments", "Virtual Environment", "\U0001f40d"),
    ".nox": ("Nox Environments", "Virtual Environment", "\U0001f40d"),
    "venv": ("Python Virtualenv", "Virtual Environment", "\U0001f4c2"),
    ".venv": ("Python Virtualenv", "Virtual Environment", "\U0001f4c2"),
    "env": ("Python Environment", "Virtual Environment", "\U0001f4c2"),
    ".eggs": ("Python Eggs", "Dependency", "\U0001f40d"),
    "site-packages": ("Python Site Packages", "Dependency", "\U0001f40d"),
    "dist-info": ("Python Dist Info", "Dependency", "\U0001f40d"),
    # ---- Java / Kotlin / Scala / Android
    ".gradle": ("Gradle Cache", "Cache", "☕"),
    "build": ("Build Output", "Build", "⚙️"),
    "target": ("Build Output", "Build", "⚙️"),
    ".idea": ("IDE Metadata", "IDE Metadata", "\U0001f4a1"),
    ".vscode": ("Workspace Settings", "IDE Metadata", "\U0001f4a1"),
    "Pods": ("CocoaPods", "Dependency", "\U0001f4e6"),
    "DerivedData": ("Xcode Cache", "Cache", "\U0001f34e"),
    ".kotlin": ("Kotlin Cache", "Cache", "☕"),
    # ---- Rust
    "target": ("Rust Build", "Build", "\U0001f9f1"),
    # ---- Ruby
    "vendor/bundle": ("Ruby Bundler", "Dependency", "\U0001f48e"),
    ".bundle": ("Ruby Bundle Cache", "Cache", "\U0001f48e"),
    # ---- Go
    "vendor": ("Go Vendor", "Dependency", "\U0001f4e6"),
    # ---- JS / TS framework build
    ".next": ("Next.js Build", "Build", "⚙️"),
    ".nuxt": ("Nuxt Build", "Build", "⚙️"),
    ".svelte-kit": ("SvelteKit Build", "Build", "⚙️"),
    ".turbo": ("Turbo Cache", "Cache", "⚙️"),
    ".parcel-cache": ("Parcel Cache", "Cache", "⚙️"),
    # ---- Generic build / output
    "dist": ("Build Output", "Build", "⚙️"),
    "bin": ("Compiled Binaries", "Build", "⚙️"),
    "obj": ("Object Files", "Build", "⚙️"),
    "out": ("Build Output", "Build", "⚙️"),
    "release": ("Release Output", "Build", "⚙️"),
    "debug": ("Debug Output", "Build", "⚙️"),
    # ---- Cloud / infra
    ".terraform": ("Terraform Cache", "Cache", "\U0001f3d7️"),
    ".terraform.d": ("Terraform Plugins", "Cache", "\U0001f3d7️"),
    ".pulumi": ("Pulumi State", "Cache", "☁️"),
    ".serverless": ("Serverless Cache", "Cache", "☁️"),
    # ---- Containers
    ".docker": ("Docker Config", "Cache", "\U0001f433"),
    # ---- macOS
    "Caches": ("macOS App Caches", "Cache", "\U0001f9f9"),
    # ---- General
    ".cache": ("General Cache", "Cache", "\U0001f9f9"),
    "cache": ("General Cache", "Cache", "\U0001f9f9"),
    "tmp": ("Temporary Files", "Temporary", "\U0001f9f9"),
    "temp": ("Temporary Files", "Temporary", "\U0001f9f9"),
    "Temp": ("Temporary Files", "Temporary", "\U0001f9f9"),
    "logs": ("Log Files", "Logs", "\U0001f4dC"),
    ".logs": ("Log Files", "Logs", "\U0001f4dC"),
    # ---- Databases
    "data": ("Database Data", "Database", "\U0001f5c4️"),
    "db": ("Database", "Database", "\U0001f5c4️"),
}


# Folders that should be summarized without recursion (size-only).
# Keep in sync with KNOWN_FOLDERS — these are the most common
# "ignore the contents, just tell me the size" cases.
SMART_SKIP_FOLDERS: frozenset = frozenset({
    # JS / TS
    "node_modules", "bower_components", "jspm_packages", "pnpm-store",
    ".yarn", ".pnpm-store",
    # Python
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "venv", ".venv", "env", ".tox", ".nox",
    "site-packages", ".eggs", "dist-info",
    # JVM
    ".gradle", "build", "target", ".idea",
    # Apple
    "Pods", "DerivedData", ".kotlin",
    # Ruby / Go
    "vendor/bundle", ".bundle", "vendor",
    # Frontend
    ".next", ".nuxt", ".svelte-kit", ".turbo", ".parcel-cache",
    # Build / output
    "dist", "bin", "obj", "out", "release", "debug",
    # Cloud
    ".terraform", ".terraform.d", ".pulumi", ".serverless",
    # Containers
    ".docker",
    # General
    ".cache", "cache", "tmp", "temp", "Temp", "logs", ".logs",
    "data", "db", "Caches",
})


# --------------------------------------------------------------------------- #
#  Extension categorization
# --------------------------------------------------------------------------- #
EXTENSION_CATEGORIES: Dict[str, str] = {
    # Media
    ".mp4": "Media", ".mkv": "Media", ".avi": "Media", ".mov": "Media",
    ".wmv": "Media", ".flv": "Media", ".webm": "Media", ".mpg": "Media",
    ".mpeg": "Media", ".m4v": "Media", ".3gp": "Media", ".ts": "Media",
    ".mp3": "Media", ".wav": "Media", ".flac": "Media", ".m4a": "Media",
    ".aac": "Media", ".ogg": "Media", ".opus": "Media", ".wma": "Media",
    ".png": "Media", ".jpg": "Media", ".jpeg": "Media", ".gif": "Media",
    ".bmp": "Media", ".svg": "Media", ".tiff": "Media", ".webp": "Media",
    ".ico": "Media", ".heic": "Media", ".raw": "Media", ".psd": "Media",
    ".ai": "Media", ".eps": "Media",
    # Archive
    ".zip": "Archive", ".tar": "Archive", ".gz": "Archive", ".rar": "Archive",
    ".7z": "Archive", ".bz2": "Archive", ".xz": "Archive", ".iso": "Archive",
    ".dmg": "Archive", ".tgz": "Archive", ".zst": "Archive", ".lz4": "Archive",
    ".cab": "Archive", ".war": "Archive", ".jar": "Archive",
    # Documents
    ".pdf": "Documents", ".docx": "Documents", ".xlsx": "Documents",
    ".pptx": "Documents", ".doc": "Documents", ".xls": "Documents",
    ".ppt": "Documents", ".txt": "Documents", ".rtf": "Documents",
    ".odt": "Documents", ".ods": "Documents", ".odp": "Documents",
    ".csv": "Documents", ".md": "Documents", ".rst": "Documents",
    ".epub": "Documents", ".mobi": "Documents",
    # Source code
    ".js": "Source Code", ".mjs": "Source Code", ".cjs": "Source Code",
    ".jsx": "Source Code", ".ts": "Source Code", ".tsx": "Source Code",
    ".py": "Source Code", ".rs": "Source Code", ".java": "Source Code",
    ".kt": "Source Code", ".kts": "Source Code", ".scala": "Source Code",
    ".cpp": "Source Code", ".cc": "Source Code", ".cxx": "Source Code",
    ".c": "Source Code", ".h": "Source Code", ".hpp": "Source Code",
    ".go": "Source Code", ".rb": "Source Code", ".php": "Source Code",
    ".cs": "Source Code", ".swift": "Source Code", ".m": "Source Code",
    ".mm": "Source Code", ".pl": "Source Code", ".lua": "Source Code",
    ".r": "Source Code", ".dart": "Source Code", ".ex": "Source Code",
    ".exs": "Source Code", ".elm": "Source Code", ".hs": "Source Code",
    ".html": "Source Code", ".htm": "Source Code", ".css": "Source Code",
    ".scss": "Source Code", ".sass": "Source Code", ".less": "Source Code",
    ".vue": "Source Code", ".svelte": "Source Code",
    ".sh": "Source Code", ".bash": "Source Code", ".zsh": "Source Code",
    ".ps1": "Source Code", ".bat": "Source Code", ".cmd": "Source Code",
    ".json": "Source Code", ".xml": "Source Code", ".yaml": "Source Code",
    ".yml": "Source Code", ".toml": "Source Code", ".ini": "Source Code",
    ".cfg": "Source Code", ".conf": "Source Code",
    ".sql": "Source Code", ".graphql": "Source Code", ".gql": "Source Code",
    # Database
    ".sqlite": "Database", ".sqlite3": "Database", ".db": "Database",
    ".mdb": "Database", ".accdb": "Database",
    # Build / Web artifacts
    ".wasm": "Build", ".map": "Source Code", ".d.ts": "Source Code",
    ".min.js": "Source Code", ".min.css": "Source Code",
    # Config
    ".toml": "Source Code", ".lock": "Build", ".sum": "Build",
    # Logs
    ".log": "Logs",
}


# --------------------------------------------------------------------------- #
#  Safety classification
# --------------------------------------------------------------------------- #
SYSTEM_FOLDERS_WINDOWS = {
    "windows", "program files", "program files (x86)", "programdata",
    "users", "system32", "syswow64", "recovery",
}
SYSTEM_FOLDERS_UNIX = {
    "library", "applications", "etc", "usr", "bin", "sys", "proc",
    "dev", "var", "sbin", "root", "boot", "lib", "lib64", "opt",
}
SYSTEM_PREFIX_UNIX = (
    "/usr", "/etc", "/bin", "/sys", "/proc", "/dev", "/var",
    "/sbin", "/system", "/library", "/applications", "/boot",
)


def get_safety_status(path: Path) -> Optional[str]:
    """Return 'SYSTEM' for paths the user should never delete, else None."""
    try:
        name_lower = path.name.lower()
    except Exception:
        return None

    if os.name == "nt":
        # On Windows also flag drive roots like C:\ and the root of any drive
        if path.parent == path:
            return "SYSTEM"
        if name_lower in SYSTEM_FOLDERS_WINDOWS:
            return "SYSTEM"
    else:
        if name_lower in SYSTEM_FOLDERS_UNIX:
            return "SYSTEM"
        try:
            resolved = str(path.resolve())
            for prefix in SYSTEM_PREFIX_UNIX:
                if resolved == prefix or resolved.startswith(prefix + "/"):
                    return "SYSTEM"
        except Exception:
            pass
    return None


# --------------------------------------------------------------------------- #
#  Public API
# --------------------------------------------------------------------------- #
_CATEGORY_ICONS: Dict[str, str] = {
    "Media": "\U0001f3ac",
    "Archive": "\U0001f4e6",
    "Documents": "\U0001f4c4",
    "Source Code": "\U0001f4bb",
    "Logs": "\U0001f4dC",
    "Database": "\U0001f5c4️",
}


def analyze_entry(path: Path, is_dir: bool) -> Tuple[str, str, str, Optional[str]]:
    """Return (reason, category, icon, safety) for a single entry."""
    safety = get_safety_status(path)

    if is_dir:
        name = path.name
        if name in KNOWN_FOLDERS:
            reason, category, icon = KNOWN_FOLDERS[name]
            return reason, category, icon, safety

        # Special case: Drive roots & system markers
        if safety == "SYSTEM":
            return "System Root", "SYSTEM", "⚠️", safety

        return "—", "Unknown", "", safety

    # File path
    ext = path.suffix.lower()
    if ext in EXTENSION_CATEGORIES:
        category = EXTENSION_CATEGORIES[ext]
        icon = _CATEGORY_ICONS.get(category, "")
        return "—", category, icon, safety
    return "—", "Unknown", "", safety


def get_folder_meta(name: str) -> Optional[Tuple[str, str, str]]:
    """Look up (reason, category, icon) for a known folder name."""
    return KNOWN_FOLDERS.get(name)


def age_bucket(mtime: float, now: float) -> str:
    """Bucket a file/dir into a coarse age range."""
    if mtime <= 0:
        return "unknown"
    age_days = max(0.0, (now - mtime) / 86400.0)
    if age_days < 1:
        return "< 1 day"
    if age_days < 7:
        return "1-7 days"
    if age_days < 30:
        return "1-4 weeks"
    if age_days < 90:
        return "1-3 months"
    if age_days < 365:
        return "3-12 months"
    if age_days < 730:
        return "1-2 years"
    return "> 2 years"