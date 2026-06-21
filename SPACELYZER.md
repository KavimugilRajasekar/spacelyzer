# Spacelyzer — Developer Documentation

> **Read-only disk analyzer.** Spacelyzer never modifies your filesystem. It tells you where your storage is being used, explains why, finds similar files and folders, and provides full absolute paths so you can take action yourself.

---

## Table of Contents

1. [Philosophy](#1-philosophy)
2. [Project Overview](#2-project-overview)
3. [Core Architecture — The 9 Pillars](#3-core-architecture--the-9-pillars)
4. [CLI Reference](#4-cli-reference)
5. [Output Formats](#5-output-formats)
6. [Output Design Specification](#6-output-design-specification)
7. [Known Storage Patterns](#7-known-storage-patterns)
8. [Exit Codes](#8-exit-codes)
9. [Roadmap (v2+)](#9-roadmap-v2)

---

## 1. Philosophy

```
Analyze → Explain → Suggest → Show Paths → User Decides
```

Spacelyzer answers four questions no other disk analyzer answers together:

- **Where** is my storage going?
- **Why** is it there?
- **Is there another copy** somewhere?
- **How do I reach it** to act on it?

It is strictly a **read-only** tool. There is no delete button. By printing full absolute paths, users can `Ctrl+Click` (or `Cmd+Click` on macOS) in modern terminals to open the location themselves.

---

## 2. Project Overview

### Basic Syntax

```
spacelyzer [PATH] [OPTIONS]
```

If no path is given, defaults to the current working directory (`.`).

### Quick Examples

```bash
# Analyze current folder
spacelyzer

# Analyze Downloads
spacelyzer ~/Downloads

# Analyze a Windows drive
spacelyzer C:\

# Analyze with depth and top-N limit
spacelyzer ~/Projects -d 2 --top 10

# Include files, show tree view
spacelyzer ~/Projects --files --tree

# Find duplicate/similar files
spacelyzer ~/Projects --similar

# Show extension breakdown
spacelyzer ~/Projects --extensions

# Export as JSON
spacelyzer ~/Projects --json
```

---

## 3. Core Architecture — The 9 Pillars

### Pillar 1 — Disk Usage Analysis

The foundation. Every scan produces:

| Field | Description |
|---|---|
| Rank | Ordered by size descending (default) |
| Type | `DIR` or `FILE` |
| Size | Human-readable (e.g. `18.2 GB`) or raw bytes with `--bytes` |
| Share | Percentage of total scanned size |
| Category | Semantic label (see [Pillar 4](#pillar-4--storage-categories)) |
| Reason | Human-readable annotation (e.g. `Node Modules`, `Python Cache`) |
| Safety | `SYSTEM` flag for OS-critical paths (see [Pillar 1 Safety](#safety-flags)) |
| Icon | Optional emoji prefix for quick visual scanning |
| Path | Full absolute path — always |

**Example output:**

```
Rank  Type   Size      Category      Reason          Path
──────────────────────────────────────────────────────────────────────────────────────
1      DIR  18.4 GB   Dependency    Node Modules    /home/kavi/projects/app/node_modules
2      DIR   6.1 GB   Cache         Python Cache    /home/kavi/projects/app/__pycache__
3      FILE  4.0 GB   Archive       —               /home/kavi/downloads/ubuntu.iso
4      DIR  42.0 GB  SYSTEM        System Root     /usr
```

#### Safety Flags

Certain directories are marked `SYSTEM` and should never be deleted:

**Windows:** `Windows`, `Program Files`, `Program Files (x86)`, `Users`, `System32`

**macOS/Linux:** `Library`, `Applications`, `/etc`, `/usr`, `/bin`, `/sys`, `/proc`

---

### Pillar 2 — Similar Files & Folders

Detects redundant storage across three levels of similarity.

#### Detection Modes

| Mode | Method | Match Criteria |
|---|---|---|
| Exact Duplicate | SHA-256 hash | 100% identical content |
| Similar File | Fuzzy hash + metadata | Same name, extension, approximate size |
| Similar Folder | Name + structure matching | Same folder name appearing in multiple locations |

#### Similar File Output

```
Similarity Group #1  ·  3 Files  ·  9.3 GB total

  movie.mp4           3.1 GB    /home/kavi/downloads/movie.mp4
  movie (1).mp4       3.1 GB    /home/kavi/backup/movie (1).mp4
  movie_copy.mp4      3.1 GB    /media/external/movie_copy.mp4
```

#### Similar Folder Output

```
Found 3 similar folders — "node_modules"  ·  15.2 GB combined

  /home/kavi/projects/app/node_modules        5.1 GB
  /home/kavi/projects/website/node_modules    5.0 GB
  /home/kavi/projects/old-backup/node_modules 5.1 GB
```

---

### Pillar 3 — Common Storage Consumers

Spacelyzer tracks well-known storage hogs across the entire scan and groups them by name:

```
Found across scan:
  12 × node_modules     →  28.0 GB
  18 × __pycache__      →  830 MB
   7 × dist             →  4.1 GB
   5 × build            →  2.8 GB
   3 × target           →  1.9 GB
   2 × venv             →  1.4 GB
```

---

### Pillar 4 — Storage Categories

Spacelyzer classifies every entry into a semantic category:

| Category | Examples |
|---|---|
| Dependency | `node_modules`, `Pods` |
| Cache | `__pycache__`, `.gradle`, `DerivedData`, `.terraform` |
| Build | `dist`, `build`, `target`, `bin`, `obj`, `.next`, `.nuxt` |
| Virtual Environment | `venv`, `.venv`, `env` |
| IDE Metadata | `.idea`, `.vscode` |
| Temporary | `tmp`, `Temp`, `.cache` |
| Media | Video, audio, image files |
| Archive | `.zip`, `.iso`, `.tar`, `.gz` |
| Documents | `.pdf`, `.docx`, `.xlsx` |
| Source Code | `.js`, `.py`, `.rs`, `.java`, etc. |
| Unknown | Everything else |

**Category summary view** (`--summary`):

```
Dependency          38 GB   ████████████████████████
Cache               11 GB   ███████
Media               52 GB   ████████████████████████████████
Archives            24 GB   ████████████████
Virtual Envs         9 GB   ██████
Documents            3 GB   ██
```

---

### Pillar 5 — Hierarchical Tree View

`--tree` renders the directory hierarchy with cumulative sizes:

```
Projects                   62 GB
├── Videos                 28 GB
│   ├── Anime              18 GB
│   └── Movies             10 GB
├── node_modules           16 GB
├── Downloads               9 GB
└── Backup                  9 GB
```

---

### Pillar 6 — Terminal Visualizations

Four visualization modes, all rendered in the terminal.

#### Bar Chart (default visual, `--bar`)

```
Videos        ██████████████████████  58%
Downloads     ████████                19%
Cache         ████                    10%
Projects      ███                      8%
Others        ██                       5%
```

#### Sunburst / ASCII Tree (`--sunburst`)

```
Disk  100%
│
├──────── Videos              58%
│      ├──── Movies           30%
│      ├──── Anime            20%
│      └──── Clips             8%
│
├──────── Downloads           20%
├──────── Cache               10%
└──────── Others              12%
```

#### Terminal Treemap (`--treemap`)

```
████████████████████████████████████████████████
████████  Videos 58%  ████████████████████████
████  Downloads 19%  ████  Cache 10%  Others ██
████████████████████████████████████████████████
```

#### Unicode Pie Chart (`--pie`)

```
Storage Distribution

◜██████████◝  Videos      58%
◜█████◞       Downloads   19%
◜███◝         Cache       10%
              Others      13%
```

---

### Pillar 7 — Intelligent Suggestions

Displayed at the end of every scan. Wording is deliberately cautious — "potentially reclaimable" rather than "safe to delete," since that depends on the user's workflow.

```
Suggestions
────────────────────────────────────────────────────────────

✓  Found 18 node_modules folders           →  31.2 GB potentially reclaimable
✓  Found 21 __pycache__ folders            →  720 MB potentially reclaimable
✓  Found 8 build/dist folders              →  4.8 GB potentially reclaimable
✓  Found 14 duplicate ISO files            →  22 GB potentially reclaimable
✓  Found 37 temporary folders              →  3.4 GB potentially reclaimable

No action was performed.
────────────────────────────────────────────────────────────
Total potentially reclaimable:  62.1 GB
```

---

### Pillar 8 — Path Accessibility

Every path displayed is always the **full absolute path**. Never relative, never truncated.

```
/home/kavi/projects/website/node_modules
C:\Users\Kavi\Projects\App\node_modules
```

This enables `Ctrl+Click` / `Cmd+Click` navigation in:
- Windows Terminal
- VS Code integrated terminal
- iTerm2
- Most modern Linux terminals

---

### Pillar 9 — Scan Summary

```
────────────────────────────────────────────────────────────
Scan Completed

  Folders scanned          18,420
  Files scanned           162,318
  Unique extensions            412
  Largest folder           Videos
  Largest file          movie.mkv
  Largest duplicate group   8 files
  Total duplicate size        42 GB
  Potentially reclaimable     58 GB
  Elapsed time             12.8 sec
────────────────────────────────────────────────────────────
```

---

## 4. CLI Reference

### Arguments

| Argument | Description |
|---|---|
| `PATH` | Directory to analyze. Defaults to `.` if omitted. |

### Core Options

| Flag | Alias | Description |
|---|---|---|
| `--depth <n>` | `-d` | Limit recursion to `n` levels deep |
| `--top <n>` | `-n` | Show only the largest `n` entries |
| `--files` | `-f` | Include files in results (default: folders only) |
| `--folders` | | Show folders only, ignore files entirely |
| `--hidden` | | Include hidden files and folders (default: excluded) |
| `--follow-links` | | Follow symbolic links (default: no) |
| `--sort <key>` | | Sort by `size` (default), `name`, or `modified` |
| `--reverse` | `-r` | Reverse sort order (ascending) |
| `--min <size>` | | Ignore entries smaller than threshold, e.g. `100MB`, `1GB` |
| `--bytes` | | Show raw byte counts instead of human-readable sizes |
| `--ignore <pattern>` | | Exclude paths matching pattern. Repeatable. e.g. `--ignore node_modules --ignore "*.cache"` |

### Analysis Modes

| Flag | Description |
|---|---|
| `--tree` | Render hierarchical tree view with sizes |
| `--largest-files` | List the largest individual files |
| `--extensions` | Group and rank by file extension |
| `--breakdown` | Show percentage breakdown of a folder's contents |
| `--similar` | Detect similar and duplicate files/folders |
| `--summary` | Show storage category summary |
| `--fingerprint` | Show Storage Fingerprint (see below) |

### Visualization Flags

| Flag | Description |
|---|---|
| `--bar` | Terminal bar chart (default visual) |
| `--pie` | Unicode pie chart |
| `--sunburst` | ASCII sunburst tree |
| `--treemap` | Terminal treemap grid |

### Output Format Flags

| Flag | Description |
|---|---|
| `--json` | Output as JSON |
| `--csv` | Output as CSV |
| `--markdown` | Output as Markdown table |

### Other

| Flag | Description |
|---|---|
| `--help` | Show help and exit |
| `--version` | Show version and exit |

---

## 5. Output Formats

### Terminal (default)

Renders a styled table with Unicode box-drawing characters, icons, and a progress indicator during scanning.

**Progress indicator:**

```
Scanning...  █████████████████░░░░░  72%  ·  12,830 folders scanned
```

### JSON (`--json`)

```json
{
  "path": "/home/kavi/projects",
  "depth": 2,
  "total_size_bytes": 50239078400,
  "elapsed_seconds": 2.14,
  "entries": [
    {
      "rank": 1,
      "type": "DIR",
      "name": "node_modules",
      "path": "/home/kavi/projects/app/node_modules",
      "size_bytes": 19537526784,
      "size_human": "18.2 GB",
      "share_percent": 38.9,
      "category": "Dependency",
      "reason": "Node Modules",
      "icon": "📦",
      "safety": null
    }
  ],
  "summary": {
    "folders_scanned": 1243,
    "files_scanned": 27981,
    "largest_folder": "node_modules",
    "largest_file": "ubuntu.iso",
    "potentially_reclaimable_bytes": 62709653504
  }
}
```

### CSV (`--csv`)

```
rank,type,name,size_bytes,size_human,share_percent,category,reason,safety,path
1,DIR,node_modules,19537526784,18.2 GB,38.9,Dependency,Node Modules,,/home/kavi/projects/app/node_modules
```

### Markdown (`--markdown`)

```markdown
| # | Type | Size | Share | Category | Path |
|---|------|------|-------|----------|------|
| 1 | DIR | 18.2 GB | 38.9% | Dependency | /home/kavi/projects/app/node_modules |
```

---

## 6. Output Design Specification

### Main Table

```
 Path      : /home/kavi/Projects
 Depth     : 2
 Folders   : 1,243
 Files     : 27,981
 Total     : 46.8 GB
 Elapsed   : 2.14 s

┌────┬──────┬──────────┬────────┬──────────────┬────────────────────────────────────────────┐
│ #  │ Type │ Size     │ Share  │ Category     │ Path                                       │
├────┼──────┼──────────┼────────┼──────────────┼────────────────────────────────────────────┤
│ 1  │   DIR│ 18.2 GB  │ 38.9%  │ Dependency   │ /home/kavi/projects/app/node_modules       │
│ 2  │   DIR│  8.4 GB  │ 17.9%  │ Media        │ /home/kavi/videos                          │
│ 3  │   DIR│  6.1 GB  │ 13.0%  │ Cache        │ /home/kavi/projects/app/__pycache__        │
│ 4  │  FILE│  3.9 GB  │  8.3%  │ Archive      │ /home/kavi/downloads/ubuntu.iso            │
│ 5  │   DIR│  2.8 GB  │  6.0%  │ Temporary    │ /home/kavi/.cache                          │
└────┴──────┴──────────┴────────┴──────────────┴────────────────────────────────────────────┘
```

### Storage Fingerprint (`--fingerprint`)

A distinctive Spacelyzer feature. Instead of just listing folders, recognizes the *kind* of developer or user based on what's on disk:

```
🧩 Storage Fingerprint
────────────────────────────────────────────────────────

  JavaScript Development   █████████████   32 GB
  Python Development       █████           11 GB
  Rust Projects            ███              6 GB
  Android Development      ████             9 GB
  Docker Data              ██████          14 GB
  Media Library            ██████████      41 GB
  Archives                 ████            18 GB
```

### Largest Files (`--largest-files`)

```
  1   movie.mkv       3.4 GB    /home/kavi/videos/movie.mkv
  2   backup.zip      2.1 GB    /home/kavi/backup/backup.zip
  3   setup.iso       1.2 GB    /home/kavi/downloads/setup.iso
```

### Extension Breakdown (`--extensions`)

```
Extension     Total Size    Files
──────────────────────────────────
.mp4          24 GB         312
.zip          13 GB          47
.iso          11 GB           8
.exe           6 GB         203
.pdf         900 MB         991
```

### Folder Breakdown (`--breakdown`)

```
Downloads
├── Videos      48%  ████████████████████████
├── Images      20%  ██████████
├── Documents   15%  ███████
├── Archives    10%  █████
└── Others       7%  ████
```

---

## 7. Known Storage Patterns

Spacelyzer recognizes and annotates these well-known directories automatically:

| Folder | Reason Label | Category | Icon |
|---|---|---|---|
| `node_modules` | Node Modules | Dependency | 📦 |
| `__pycache__` | Python Cache | Cache | 🐍 |
| `.pytest_cache` | Pytest Cache | Cache | 🐍 |
| `.mypy_cache` | MyPy Cache | Cache | 🐍 |
| `.ruff_cache` | Ruff Cache | Cache | 🐍 |
| `.next` | Next.js Build | Build | ⚙️ |
| `.nuxt` | Nuxt Build | Build | ⚙️ |
| `dist` | Build Output | Build | ⚙️ |
| `build` | Build Output | Build | ⚙️ |
| `target` | Rust Build | Build | 🧱 |
| `bin` | Compiled Binaries | Build | ⚙️ |
| `obj` | Object Files | Build | ⚙️ |
| `.gradle` | Gradle Cache | Cache | ☕ |
| `.idea` | IDE Metadata | IDE | 💡 |
| `.vscode` | Workspace Settings | IDE | 💡 |
| `venv` | Python Virtualenv | Virtual Env | 🗂️ |
| `.venv` | Python Virtualenv | Virtual Env | 🗂️ |
| `env` | Python Environment | Virtual Env | 🗂️ |
| `Pods` | CocoaPods | Dependency | 📦 |
| `DerivedData` | Xcode Cache | Cache | 🍎 |
| `.terraform` | Terraform Cache | Cache | 🏗️ |
| `.cache` | General Cache | Cache | 🧹 |
| `tmp` / `Temp` | Temporary Files | Temporary | 🧹 |

---

## 8. Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Unknown error |
| `2` | Permission denied |
| `3` | Path not found |
| `4` | Cancelled by user |

---

## 9. Roadmap (v2+)

| Feature | Flag | Description |
|---|---|---|
| Exact Duplicate Detection | `--duplicates` | Find byte-identical files using SHA-256 hashing |
| Snapshot Comparison | `--compare <old.json>` | Diff a previous scan against the current one |
| Live Monitoring | `--watch` | Refresh disk usage automatically at an interval |
| Interactive HTML Report | `--export html` | Generate a rich HTML report with charts |
| Scan History | `--history` | Keep and browse historical snapshots |
| Gitignore Integration | `--gitignore` | Skip files matched by the nearest `.gitignore` |
| Parallel Scanning | `--parallel` | Multi-threaded scan for large directories |
| Scan Cache | `--cache` | Cache results to speed up repeated scans |

---

*Spacelyzer — Analyze first. Act manually.*
