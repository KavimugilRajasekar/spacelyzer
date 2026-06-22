# Spacelyzer — Developer Documentation

> **Read-only disk analyzer.** Spacelyzer never modifies your filesystem. It tells you where your storage is being used, explains why, finds similar files and folders, and provides full absolute paths so you can take action yourself.

---

## Table of Contents

1. [Philosophy](#1-philosophy)
2. [Project Overview](#2-project-overview)
3. [Core Architecture — The 12 Pillars](#3-core-architecture--the-12-pillars)
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
spacelyzer [analyze] [PATH] [OPTIONS]
spacelyzer <subcommand> [PATH] [OPTIONS]
```

Subcommands: `analyze` (default), `snapshot`, `history`, `diff`, `watch`, `duplicates`, `report`.

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

# Find byte-identical duplicates
spacelyzer duplicates ~/Projects --hash sha256

# Save, list, and diff snapshots
spacelyzer snapshot ~/Projects --label week-1
spacelyzer snapshot ~/Projects --label week-2
spacelyzer diff ~/Projects --with ~/.spacelyzer/snapshots/<week-1>.json

# Live monitoring
spacelyzer watch ~/Downloads --interval 5s --iterations 10

# Export as JSON
spacelyzer ~/Projects --format json
```

---

## 3. Core Architecture — The 12 Pillars

### Pillar 1 — Disk Usage Analysis

The foundation. Every scan produces:

| Field | Description |
|---|---|
| Rank | Ordered by size descending (default) |
| Type | `DIR`, `DIR*` (smart-summarized), or `FILE` |
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

**Windows:** `Windows`, `Program Files`, `Program Files (x86)`, `Users`, `System32`, `ProgramData`, `Recovery`, `SysWOW64`

**macOS/Linux:** `Library`, `Applications`, `/etc`, `/usr`, `/bin`, `/sys`, `/proc`, `/dev`, `/var`, `/sbin`, `/boot`, `/lib`, `/lib64`, `/opt`, `/root`

---

### Pillar 2 — Similar Files & Folders

Detects redundant storage across three levels of similarity.

#### Detection Modes

| Mode | Method | Match Criteria |
|---|---|---|
| Exact Duplicate | BLAKE2b-256 (or SHA-256) | 100% identical content |
| Similar File | Fuzzy match + metadata | Same basename, size within ±10 % |
| Similar Folder | Name matching | Same folder name appearing in multiple locations |

`find_exact_duplicates` does a three-stage pipeline: bucket by size → partial-hash the first 64 KiB → full content hash. This makes dedup dramatically faster on large folders with few common sizes.

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
| Dependency | `node_modules`, `Pods`, `bower_components`, `jspm_packages` |
| Cache | `__pycache__`, `.gradle`, `DerivedData`, `.terraform`, `.turbo` |
| Build | `dist`, `build`, `target`, `bin`, `obj`, `.next`, `.nuxt` |
| Virtual Environment | `venv`, `.venv`, `env`, `.tox`, `.nox` |
| IDE Metadata | `.idea`, `.vscode` |
| Temporary | `tmp`, `Temp`, `.cache`, `cache` |
| Logs | `logs`, `.logs`, `*.log` |
| Media | Video, audio, image files |
| Archive | `.zip`, `.iso`, `.tar`, `.gz` |
| Documents | `.pdf`, `.docx`, `.xlsx` |
| Source Code | `.js`, `.py`, `.rs`, `.java`, etc. |
| Database | `data/`, `db/`, `*.sqlite`, `*.db` |
| System | OS-critical roots (`/usr`, `C:\Windows`, …) |
| Unknown | Everything else |

**Category summary view** (`--summary` or `--categories`):

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

`--tree` renders the directory hierarchy with cumulative sizes. Smart-summarized folders appear as `DIR*` leaves with a "(size only)" annotation:

```
Projects                   62 GB
├── Videos                 28 GB
│   ├── Anime              18 GB
│   └── Movies             10 GB
├── node_modules*          16 GB   (size only)
├── __pycache__*            6 GB   (size only)
├── Downloads               9 GB
└── Backup                  9 GB
```

Pass `--no-smart-skip` to fully recurse and expand the `*` nodes.

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
  Smart-summarized            412
  Unique extensions            412
  Largest folder           Videos
  Largest file          movie.mkv
  Largest duplicate group   8 files
  Total duplicate size        42 GB
  Potentially reclaimable     58 GB
  Avg file size             124 KB
  Median file size           18 KB
  Elapsed time             12.8 sec
────────────────────────────────────────────────────────────
```

---

### Pillar 10 — Smart-Skip

Well-known huge folders (`node_modules`, `__pycache__`, `target`, `dist`, `build`, `.gradle`, `venv`, `.next`, …) are summarized by size only — never fully enumerated. This keeps scans fast and avoids creating tens of thousands of noise entries.

Each skipped folder is reported as a single `DIR*` row with a `(size only)` annotation. Disable with `--no-smart-skip` to fully recurse.

The smart-summarized size is rolled up into the parent folder's total so the reported **Total** is accurate even with smart-skip on.

---

### Pillar 11 — Snapshots & Diff

Save a scan, list past scans, and compare two of them.

```bash
# Save a snapshot (file: ~/.spacelyzer/snapshots/<safe_name>__<timestamp>.json)
spacelyzer snapshot ~/Projects --label baseline

# List snapshots for a path
spacelyzer history ~/Projects
spacelyzer history ~/Projects --json

# Diff a saved snapshot against the latest one
spacelyzer diff ~/Projects --with ~/.spacelyzer/snapshots/<baseline>.json --top 20
```

Diff output shows added/removed entries and the top movers by absolute size delta.

---

### Pillar 12 — Watch Mode

`spacelyzer watch [PATH] [--interval 5s] [--iterations N]` re-runs the analysis at a fixed interval and re-renders in place. `Ctrl+C` stops the loop. Use `--iterations` to bound long-running watches in scripts.

---

## 4. CLI Reference

### Subcommands

| Subcommand | Description |
|---|---|
| `analyze [PATH]` | Default. Run a single analysis pass. |
| `snapshot [PATH]` | Run a scan and persist a snapshot. |
| `history [PATH]` | List snapshots previously saved for a path. |
| `diff [PATH] --with <file>` | Compare two snapshots. |
| `watch [PATH]` | Re-scan and re-render at a fixed interval. |
| `duplicates [PATH]` | Find byte-identical files (full content hash). |
| `report [PATH]` | Write a self-contained HTML report. |

### Arguments

| Argument | Description |
|---|---|
| `PATH` | Directory to analyze. Defaults to `.` if omitted. |

### Core Options (shared by `analyze`, `snapshot`, `watch`, `duplicates`, `report`)

| Flag | Alias | Description |
|---|---|---|
| `--depth <n>` | `-d` | Limit recursion depth. |
| `--top <n>` | `-n` | Show only the top N entries. |
| `--files` | `-f` | Include files in results (default: folders only). |
| `--folders` | | Show folders only, ignore files entirely. |
| `--hidden` | | Include hidden files and folders (default: excluded). |
| `--follow-links` | | Follow symbolic links (default: no). |
| `--sort <key>` | | Sort by `size` (default), `name`, or `modified`. |
| `--reverse` | `-r` | Reverse sort order (ascending). |
| `--min <size>` | | Ignore entries smaller than size (e.g. `100MB`, `1GB`). |
| `--max <size>` | | Ignore entries larger than size (0 = unlimited). |
| `--bytes` | | Show raw byte counts instead of human-readable sizes. |
| `--ignore <pattern>` | | Exclude paths matching pattern. Repeatable. |
| `--gitignore` | | Respect nearest `.gitignore` at every level. |
| `--query <regex>` | | Regex matched against entry name. |
| `--ext <ext>` | | Limit to specific extensions. Repeatable. |
| `--newer-than <age>` | | Only entries modified in the last N (e.g. `30d`, `12h`). |
| `--older-than <age>` | | Only entries older than N (e.g. `90d`, `1y`). |
| `--workers <n>` | | Number of scanner workers (0 = auto). |
| `--no-progress` | | Suppress the scanning progress indicator. |
| `--include-age` | | Show the mtime-age column in the main table. |
| `--no-smart-skip` | | Recurse into `node_modules`, `__pycache__`, `target`, etc. |
| `--output <path>` | `-o` | Write output to this file instead of stdout. |
| `--format <fmt>` | | `table` (default), `json`, `csv`, `ndjson`, `yaml`, `markdown`, `html`. |

### Analysis Modes

| Flag | Description |
|---|---|
| `--tree` | Render hierarchical tree view with sizes |
| `--compact` | Compact table layout for narrow terminals |
| `--largest-files` | List the largest individual files |
| `--extensions` | Group and rank by file extension |
| `--breakdown` | Show percentage breakdown of a folder's contents |
| `--similar` | Detect similar and duplicate files/folders |
| `--summary` | Show storage category bar graph plus storage fingerprint |
| `--fingerprint` | Show Storage Fingerprint |
| `--age` | Show age-distribution buckets |
| `--categories` | Show storage-category summary bars |

### Visualization Flags

| Flag | Description |
|---|---|
| `--bar` | Terminal bar chart (default visual) |
| `--pie` | Unicode pie chart |
| `--sunburst` | ASCII sunburst tree |
| `--treemap` | Terminal treemap grid |

### Subcommand-Specific Flags

| Subcommand | Flag | Description |
|---|---|---|
| `snapshot` | `--label <name>` | Friendly name for the snapshot. |
| `history` | `--json` | Emit history as JSON. |
| `diff` | `--with <file>` | Path to a previous snapshot file. |
| `diff` | `--top <n>` | Show the top N movers (default: 20). |
| `watch` | `--interval <dur>` | Seconds between re-scans (e.g. `5s`, `1m`). |
| `watch` | `--iterations <n>` | Stop after this many ticks (default: forever). |
| `duplicates` | `--hash <algo>` | Hash algorithm: `blake2b` (default, ~3× faster) or `sha256`. |
| `duplicates` | `--top <n>` | Show the top N duplicate groups. |
| `report` | `-o, --output <path>` | Override the default report output path. |

### Other

| Flag | Description |
|---|---|
| `--help` | Show help and exit |
| `--version` | Show version and exit |

---

## 5. Output Formats

### Terminal (default)

Renders a styled table with Unicode box-drawing characters, icons, and a progress indicator during scanning. The output is TTY-aware — colors and Unicode are auto-disabled on non-TTY pipes and ASCII-only terminals.

**Progress indicator:**

```
Scanning...  ⠹  12,830 folders scanned, 102,341 files scanned
```

### JSON (`--format json`)

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
      "safety": null,
      "smart_summary": false
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

### CSV (`--format csv`)

```
rank,type,name,size_bytes,size_human,share_percent,category,reason,safety,modified,path,smart_summary
1,DIR,node_modules,19537526784,18.2 GB,38.9,Dependency,Node Modules,,2025-06-10 12:34:56,/home/kavi/projects/app/node_modules,0
```

### NDJSON (`--format ndjson`)

One JSON object per line — first line is `_meta`, then one per entry. Streamable for `jq` pipelines.

### YAML (`--format yaml`)

Minimal YAML emitter (no PyYAML dependency required).

### Markdown (`--format markdown`)

| # | Type | Size | Share | Category | Path |
|---|------|------|-------|----------|------|
| 1 | DIR | 18.2 GB | 38.9% | Dependency | /home/kavi/projects/app/node_modules |

### HTML (`--format html` or `spacelyzer report`)

Self-contained single-file HTML with inline CSS, a categories table, and a top-entries table. No JavaScript, no external assets.

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

### Smart-Skip Notice

The default output prints a dedicated "Smart-Summarized Folders" section listing the top 15 by size, with a `--no-smart-skip` hint to fully recurse.

### Age Distribution (`--age`)

```
Age Distribution

< 1 day              12 MB       2  ▓
1-7 days            180 MB      14  ▓▓▓
1-4 weeks             2 GB     117  ▓▓▓▓▓▓▓▓▓▓▓▓▓
1-3 months            5 GB     240  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
3-12 months          16 GB     910  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
```

---

## 7. Known Storage Patterns

Spacelyzer recognizes and annotates these well-known directories automatically:

| Folder | Reason Label | Category | Icon |
|---|---|---|---|
| `node_modules` | Node Modules | Dependency | 📦 |
| `bower_components` | Bower Components | Dependency | 📦 |
| `jspm_packages` | JSPM Packages | Dependency | 📦 |
| `pnpm-store` | pnpm Store | Dependency | 📦 |
| `__pycache__` | Python Cache | Cache | 🐍 |
| `.pytest_cache` | Pytest Cache | Cache | 🐍 |
| `.mypy_cache` | MyPy Cache | Cache | 🐍 |
| `.ruff_cache` | Ruff Cache | Cache | 🐍 |
| `.tox` / `.nox` | Tox/Nox Environments | Virtual Environment | 🐍 |
| `venv` / `.venv` | Python Virtualenv | Virtual Env | 🗂️ |
| `env` | Python Environment | Virtual Env | 🗂️ |
| `.eggs` | Python Eggs | Dependency | 🐍 |
| `site-packages` | Python Site Packages | Dependency | 🐍 |
| `.next` | Next.js Build | Build | ⚙️ |
| `.nuxt` | Nuxt Build | Build | ⚙️ |
| `.svelte-kit` | SvelteKit Build | Build | ⚙️ |
| `.turbo` | Turbo Cache | Cache | ⚙️ |
| `.parcel-cache` | Parcel Cache | Cache | ⚙️ |
| `dist` | Build Output | Build | ⚙️ |
| `build` | Build Output | Build | ⚙️ |
| `target` | Rust Build | Build | 🧱 |
| `bin` | Compiled Binaries | Build | ⚙️ |
| `obj` | Object Files | Build | ⚙️ |
| `out` | Build Output | Build | ⚙️ |
| `release` / `debug` | Release / Debug Output | Build | ⚙️ |
| `.gradle` | Gradle Cache | Cache | ☕ |
| `.idea` | IDE Metadata | IDE | 💡 |
| `.vscode` | Workspace Settings | IDE | 💡 |
| `Pods` | CocoaPods | Dependency | 📦 |
| `DerivedData` | Xcode Cache | Cache | 🍎 |
| `.kotlin` | Kotlin Cache | Cache | ☕ |
| `vendor/bundle` | Ruby Bundler | Dependency | 💎 |
| `.bundle` | Ruby Bundle Cache | Cache | 💎 |
| `vendor` | Go Vendor | Dependency | 📦 |
| `.terraform` / `.terraform.d` | Terraform Cache | Cache | 🏗️ |
| `.pulumi` | Pulumi State | Cache | ☁️ |
| `.serverless` | Serverless Cache | Cache | ☁️ |
| `.docker` | Docker Config | Cache | 🐳 |
| `Caches` | macOS App Caches | Cache | 🧹 |
| `.cache` / `cache` | General Cache | Cache | 🧹 |
| `tmp` / `temp` / `Temp` | Temporary Files | Temporary | 🧹 |
| `logs` / `.logs` | Log Files | Logs | 📜 |
| `data` | Database Data | Database | 🗄️ |
| `db` | Database | Database | 🗄️ |

---

## 8. Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Unknown / unexpected error |
| `2` | Permission denied |
| `3` | Path not found |
| `4` | Cancelled by user (Ctrl+C or `UserCancelledException`) |

Every subcommand routes through a **global exception guard** inside `main()`, so the user always sees a clean, single-line error message on `stderr` instead of a raw Python traceback.

### Interrupt behaviour

| Where the interrupt happens | Result |
|---|---|
| During `scanner.scan()` — parallel worker | `KeyboardInterrupt` flips an internal `_cancelled` flag; partial results are committed; `UserCancelledException` is raised; CLI exits with code **4** |
| During rendering / argument parsing | `KeyboardInterrupt` is caught by `main()` guard; CLI exits with code **4** |
| In `watch` mode | `KeyboardInterrupt` or `UserCancelledException` — watch loop stops immediately; `[watch stopped by user]` is printed |

---

## 8a. Output Ordering Guarantees

All ranked outputs (main table, similarity groups, suggestions, smart-skip notice) use **stable two-key sorting**:

1. **Primary key** — the value the user asked for (`size` by default).
2. **Secondary key** — full path sorted alphabetically (`str(path).lower()`), resolved before the primary sort so ties are always broken deterministically.

This means repeated runs on the same directory always produce identical output regardless of filesystem enumeration order.

## 9. Roadmap (v2+)

| Feature | Flag | Description |
|---|---|---|
| Snapshot Comparison | `spacelyzer diff <path> --with <old.json>` | Diff a previous scan against the current one (already implemented in v2) |
| Live Monitoring | `spacelyzer watch` | Refresh disk usage automatically at an interval (already implemented in v2) |
| Interactive HTML Report | `spacelyzer report` | Generate a rich HTML report (already implemented in v2) |
| Scan History | `spacelyzer history` | Keep and browse historical snapshots (already implemented in v2) |
| Byte-identical Duplicates | `spacelyzer duplicates` | Find byte-identical files using content hashing (already implemented in v2) |
| Gitignore Integration | `--gitignore` | Skip files matched by the nearest `.gitignore` (already implemented in v2) |
| Parallel Scanning | `--workers <n>` | Multi-threaded scan for large directories (already implemented in v2) |
| Interactive TUI | `--tui` | Keyboard-driven drill-down of the scanned tree |
| Config file | `~/.spacelyzer.toml` | Persist default flags, ignore patterns, and color preferences |
| Cloud / remote scan | `spacelyzer s3://...` | Stream sizes from S3 / GCS / Azure blobs |

---

*Spacelyzer — Analyze first. Act manually.*
