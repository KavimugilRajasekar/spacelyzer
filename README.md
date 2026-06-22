# Spacelyzer

> **A powerful, read-only terminal-based disk space analyzer and similarity detector.**

Spacelyzer is a read-only disk analyzer that answers four key questions:
*   **Where** is my storage going?
*   **Why** is it there?
*   **Is there another copy** somewhere?
*   **How do I reach it** to act on it?

It is strictly a **read-only** tool. By printing full absolute paths, users can `Ctrl+Click` (or `Cmd+Click` on macOS) in modern terminals to open the location and manage files themselves.

---

## 🚀 Key Features

*   **Pillar 1: Disk Usage Analysis** - Detailed results sorted by size, share percentage, semantic category, and system-critical safety flags.
*   **Pillar 2: Similar Files & Folders** - Finds exact duplicate files (BLAKE2b / SHA-256) and similar folders (structural matching).
*   **Pillar 3: Common Storage Consumers** - Tracks and aggregates well-known space hogs (like `node_modules`, `__pycache__`, `venv`, `dist`, etc.).
*   **Pillar 4: Storage Categories** - Classifies scanned items into categories like Dependency, Cache, Build, IDE Metadata, Media, Archive, Documents, or Source Code.
*   **Pillar 5: Hierarchical Tree View** - Cumulative size calculation represented in tree layouts (with smart-skip summary nodes).
*   **Pillar 6: Terminal Visualizations** - Responsive bar charts, Sunburst ASCII trees, character-grid Treemaps, and Unicode Pie charts.
*   **Pillar 7: Intelligent Suggestions** - Highlights potentially reclaimable storage safely without deleting anything automatically.
*   **Pillar 8: Path Accessibility** - Guarantees full absolute paths for quick navigation.
*   **Pillar 9: Smart-Skip** - `node_modules`, `__pycache__`, `target`, `dist` and similar folders are summarized by size, never fully enumerated, for fast scans.
*   **Pillar 10: Snapshots & Diff** - Save scans, list history, and diff two snapshots to see what grew, shrank, was added, or removed.
*   **Pillar 11: Watch Mode** - Re-scan and re-render at a fixed interval.
*   **Pillar 12: Rich Output** - Table, JSON, CSV, NDJSON, YAML, Markdown, and self-contained HTML reports.

---

## 📦 Installation

### macOS / Linux
```bash
curl -fsSL "https://raw.githubusercontent.com/KavimugilRajasekar/spacelyzer/main/scripts/install.sh" | sh
```

### Windows (PowerShell)
```powershell
irm "https://raw.githubusercontent.com/KavimugilRajasekar/spacelyzer/main/scripts/install.ps1" | iex
```

The installers will:
* Check for required dependencies and install them if missing
* Download and install the latest spacelyzer binary to your system path
* Verify the installation with `spacelyzer --version`

*Re-run either command at any time to update to the latest version.*

> [!NOTE]
> Review the installers before running: [scripts/install.sh](https://github.com/KavimugilRajasekar/spacelyzer/blob/main/scripts/install.sh) · [scripts/install.ps1](https://github.com/KavimugilRajasekar/spacelyzer/blob/main/scripts/install.ps1)

---

## 💻 Usage

```bash
spacelyzer [PATH] [OPTIONS]
```
*If no path is specified, it defaults to the current working directory (`.`).*

The default behavior is equivalent to `spacelyzer analyze [PATH] [OPTIONS]`. Six additional subcommands are available: `analyze`, `snapshot`, `history`, `diff`, `watch`, `duplicates`, and `report`.

### Quick Examples

```bash
# Analyze the current folder
spacelyzer

# Analyze the Downloads folder
spacelyzer ~/Downloads

# Analyze with a max depth of 2 and show only top 10 items
spacelyzer ~/Projects -d 2 --top 10

# Include files in the scan and render a tree view
spacelyzer ~/Projects --files --tree

# Group and rank by file extension
spacelyzer ~/Projects --extensions

# Show duplicate or similar files and folders
spacelyzer ~/Projects --similar

# Save a snapshot, then diff against a later one
spacelyzer snapshot ~/Projects --label before
spacelyzer snapshot ~/Projects --label after
spacelyzer diff ~/Projects --with <path-to-before.json>

# Find byte-identical duplicates
spacelyzer duplicates ~/Projects

# Live monitoring
spacelyzer watch ~/Downloads --interval 5s

# Write a self-contained HTML report
spacelyzer report ~/Projects -o report.html

# Output results as JSON / CSV / NDJSON / YAML / Markdown
spacelyzer ~/Projects --format json
spacelyzer ~/Projects --format csv
spacelyzer ~/Projects --format ndjson
spacelyzer ~/Projects --format yaml
spacelyzer ~/Projects --format markdown
```

### Core CLI Options

| Flag | Alias | Description |
|---|---|---|
| `-d, --depth <n>` | `-d` | Limit recursion to `n` levels deep |
| `-n, --top <n>` | `-n` | Show only the largest `n` entries |
| `-f, --files` | `-f` | Include files in results (default: folders only) |
| `--folders` | | Show folders only, ignore files entirely |
| `--hidden` | | Include hidden files and folders (default: excluded) |
| `--follow-links` | | Follow symbolic links (default: no) |
| `--sort <key>` | | Sort by `size` (default), `name`, or `modified` |
| `-r, --reverse` | `-r` | Reverse sort order (ascending) |
| `--min <size>` | | Ignore entries smaller than threshold, e.g., `100MB`, `1GB` |
| `--max <size>` | | Ignore entries larger than threshold (0 = unlimited) |
| `--bytes` | | Show raw byte counts instead of human-readable sizes |
| `--ignore <pattern>` | | Exclude paths matching pattern (repeatable) |
| `--gitignore` | | Respect nearest `.gitignore` at every level |
| `--query <regex>` | | Regex matched against entry name |
| `--ext <ext>` | | Limit to specific extensions (repeatable) |
| `--newer-than <age>` | | Only entries modified in the last N (e.g. `30d`, `12h`) |
| `--older-than <age>` | | Only entries older than N (e.g. `90d`, `1y`) |
| `--workers <n>` | | Number of scanner workers (0 = auto) |
| `--no-progress` | | Suppress the scanning progress indicator |
| `--include-age` | | Show the mtime-age column in the main table |
| `--no-smart-skip` | | Recurse into `node_modules`, `__pycache__`, `target`, etc. |

### Analysis & Visualization Modes

*   `--tree`: Renders a hierarchical tree view with sizes.
*   `--compact`: Compact table layout for narrow terminals.
*   `--largest-files`: Lists the largest individual files.
*   `--extensions`: Groups and ranks storage by file extensions.
*   `--breakdown`: Shows percentage breakdown of a folder's contents.
*   `--similar`: Detects similar/duplicate files and folders.
*   `--summary`: Shows a storage category summary bar graph plus storage fingerprint.
*   `--fingerprint`: Shows the Developer Storage Fingerprint.
*   `--age`: Shows age-distribution buckets.
*   `--categories`: Shows storage-category summary bars.
*   `--bar` | `--pie` | `--sunburst` | `--treemap`: Terminal visualizations.

### Output Formats

`--format` accepts: `table` (default), `json`, `csv`, `ndjson`, `yaml`, `markdown`, or `html`. Use `-o, --output <path>` to write to a file instead of stdout.

### Subcommands

| Command | Description |
|---|---|
| `analyze [PATH]` | Analyze a path (default behavior; the `analyze` keyword is optional). |
| `snapshot [PATH]` | Save a snapshot of the current scan for later diffing. |
| `history [PATH]` | List snapshots previously saved for a path. |
| `diff [PATH] --with <snap.json>` | Compare two snapshots for a path. |
| `watch [PATH]` | Re-scan and re-render at a fixed interval. |
| `duplicates [PATH]` | Find byte-identical files (BLAKE2b by default, SHA-256 optional). |
| `report [PATH]` | Write a self-contained HTML report. |

Run `spacelyzer <command> --help` for command-specific flags.

### Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Unexpected error |
| `2` | Permission denied |
| `3` | Path not found |
| `4` | Cancelled by user (Ctrl+C) |

All error paths are caught by a **global exception guard** in `main()` — the user always sees a clean, single-line message on `stderr` instead of a Python traceback.

### Keyboard Interrupt / Ctrl+C

| Context | Behaviour |
|---|---|
| During `analyze`, `snapshot`, `duplicates`, `report` | Scan stops cleanly; partial results are discarded; exits with code **4** |
| During `watch` | Watch loop stops immediately; `[watch stopped by user]` is printed |
| During rendering / output | Caught by global guard; exits with code **4** |

### Output Ordering

All ranked outputs (main table, duplicate groups, suggestions, smart-skip list) are sorted with a **stable two-key strategy**: primary key first (size by default), then alphabetically by full path as a tie-breaker. Repeated runs on the same directory always produce identical output.

---

## 🗑️ Uninstallation

### macOS / Linux
```bash
curl -fsSL "https://raw.githubusercontent.com/KavimugilRajasekar/spacelyzer/main/scripts/uninstall.sh" | sh
```

### Windows (PowerShell)
```powershell
irm "https://raw.githubusercontent.com/KavimugilRajasekar/spacelyzer/main/scripts/uninstall.ps1" | iex
```

This removes the `spacelyzer` binary and cleans up any config files under `~/.spacelyzer/`. It does not remove any other tools installed on your system.

> [!NOTE]
> Review the uninstallers: [scripts/uninstall.sh](https://github.com/KavimugilRajasekar/spacelyzer/blob/main/scripts/uninstall.sh) · [scripts/uninstall.ps1](https://github.com/KavimugilRajasekar/spacelyzer/blob/main/scripts/uninstall.ps1)
