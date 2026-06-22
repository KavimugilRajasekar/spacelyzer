"""
Storage fingerprint — a richer profile of what's actually on disk.

The original version recognized 7 buckets. The enhanced version recognizes
20+, including more languages and more infra buckets.
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from spacelyzer.scanner import EntryInfo


class FingerprintCategory:
    __slots__ = ("name", "size", "details")

    def __init__(self, name: str, size: int = 0, details: str = ""):
        self.name = name
        self.size = size
        self.details = details


# Detection rules:  (label, [folder_names], icon)
_FOLDER_RULES: List[Tuple[str, Tuple[str, ...], str]] = [
    ("JavaScript / TypeScript", ("node_modules", "bower_components",
        "jspm_packages", ".next", ".nuxt", ".svelte-kit", ".turbo",
        ".parcel-cache"), "\U0001f4e6"),
    ("Python Development", ("venv", ".venv", "__pycache__",
        ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".nox",
        "site-packages", ".eggs"), "\U0001f40d"),
    ("Java / JVM", ("build", "target", ".gradle", ".idea"), "☕"),
    ("Rust Projects", ("target",), "\U0001f9f1"),
    ("Android Development", (".gradle", "Android", "AndroidStudio",
        ".kotlin"), "\U0001f4f1"),
    ("iOS / macOS", ("Pods", "DerivedData"), "\U0001f34e"),
    ("Ruby Projects", ("vendor/bundle", ".bundle"), "\U0001f48e"),
    ("Go Projects", ("vendor",), "\U0001f4e6"),
    ("C# / .NET", ("bin", "obj"), "\U0001f7e6"),
    ("Cloud / Infra", (".terraform", ".pulumi", ".serverless"), "☁️"),
    ("Docker Data", ("docker", ".docker", "containers"), "\U0001f433"),
    ("IDE / Editor State", (".idea", ".vscode", ".vs"), "\U0001f4a1"),
    ("VCS / Repo Metadata", (".git", ".svn", ".hg"), "\U0001f500"),
    ("OS Caches", ("cache", ".cache"), "\U0001f9f9"),
]


# Extension-based buckets
_EXT_RULES: List[Tuple[str, Tuple[str, ...], str]] = [
    ("Media Library", (
        ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm",
        ".mpg", ".mpeg", ".m4v", ".3gp", ".ts",
        ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma",
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".tiff", ".webp",
        ".ico", ".heic", ".raw", ".psd", ".ai", ".eps"), "\U0001f3ac"),
    ("Archives / Disk Images", (
        ".zip", ".tar", ".gz", ".rar", ".7z", ".bz2", ".xz", ".iso",
        ".dmg", ".tgz", ".zst", ".lz4", ".cab", ".war", ".jar"), "\U0001f4e6"),
    ("Documents", (
        ".pdf", ".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt", ".txt",
        ".rtf", ".odt", ".ods", ".odp", ".csv", ".md", ".rst", ".epub",
        ".mobi"), "\U0001f4c4"),
    ("Source Code", (
        ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".py", ".rs",
        ".java", ".kt", ".kts", ".scala", ".cpp", ".cc", ".cxx", ".c",
        ".h", ".hpp", ".go", ".rb", ".php", ".cs", ".swift", ".m",
        ".mm", ".pl", ".lua", ".r", ".dart", ".ex", ".exs", ".elm",
        ".hs", ".html", ".htm", ".css", ".scss", ".sass", ".less",
        ".vue", ".svelte", ".sh", ".bash", ".zsh", ".ps1", ".bat",
        ".cmd", ".json", ".xml", ".yaml", ".yml", ".toml", ".ini",
        ".cfg", ".conf", ".sql", ".graphql", ".gql"), "\U0001f4bb"),
    ("Databases", (".sqlite", ".sqlite3", ".db", ".mdb", ".accdb"),
     "\U0001f5c4️"),
    ("Logs", (".log",), "\U0001f4dC"),
]


class StorageFingerprinter:
    def __init__(self, entries: Dict[str, EntryInfo], files: Sequence[EntryInfo]):
        self.entries = entries
        self.files = files

    def get_fingerprints(self) -> List[FingerprintCategory]:
        sizes: Dict[str, int] = {}
        details: Dict[str, str] = {}

        # Folder-based
        for entry in self.entries.values():
            if not entry.is_dir:
                continue
            name = entry.name
            for label, basenames, _icon in _FOLDER_RULES:
                if name in basenames:
                    sizes[label] = sizes.get(label, 0) + entry.size
                    if label not in details:
                        details[label] = f"matched folder '{name}'"
                    break

        # File-based
        for f in self.files:
            ext = f.path.suffix.lower()
            for label, ext_set, _icon in _EXT_RULES:
                if ext in ext_set:
                    sizes[label] = sizes.get(label, 0) + f.size
                    if label not in details:
                        details[label] = f"matched extension '{ext}'"
                    break

        fingerprints = [
            FingerprintCategory(name=k, size=sizes[k], details=details.get(k, ""))
            for k in sizes if sizes[k] > 0
        ]
        fingerprints.sort(key=lambda x: x.size, reverse=True)
        return fingerprints